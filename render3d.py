"""GPU renderer for glTF figures (moderngl, OpenGL 3.3, offscreen).

One pass writes albedo, lighting (lambert and shadow-map visibility) and the
node under each pixel; the result has the same keys as the mannequin renderer,
so shadow styles, outlines and "insert on canvas" work the same way.
"""
import math
import weakref

import numpy as np

_context = None
_models = weakref.WeakSet()

VERTEX = '''
#version 330
uniform mat4 view_projection;
uniform mat4 model;
uniform bool skinned;
uniform sampler2D joint_texture;
in vec3 in_position;
in vec3 in_normal;
in vec2 in_uv;
in vec4 in_color;
in ivec4 in_joints;
in vec4 in_weights;
in float in_id;
out vec3 v_normal;
out vec3 v_world;
out vec2 v_uv;
out vec4 v_color;
flat out float v_id;
mat4 joint(int index) {
    return mat4(texelFetch(joint_texture, ivec2(index * 4, 0), 0), texelFetch(joint_texture, ivec2(index * 4 + 1, 0), 0),
                texelFetch(joint_texture, ivec2(index * 4 + 2, 0), 0), texelFetch(joint_texture, ivec2(index * 4 + 3, 0), 0));
}
void main() {
    mat4 matrix = model;
    if (skinned) {
        matrix = in_weights.x * joint(in_joints.x) + in_weights.y * joint(in_joints.y)
               + in_weights.z * joint(in_joints.z) + in_weights.w * joint(in_joints.w);
    }
    vec4 world = matrix * vec4(in_position, 1.0);
    v_world = world.xyz;
    v_normal = mat3(matrix) * in_normal;
    v_uv = in_uv;
    v_color = in_color;
    v_id = in_id;
    gl_Position = view_projection * world;
}
'''

FRAGMENT = '''
#version 330
uniform sampler2D color_texture;
uniform sampler2D shadow_map;
uniform bool has_texture;
uniform bool use_shadow;
uniform bool is_floor;
uniform bool masked;
uniform float cutoff;
uniform vec4 base_color;
uniform vec3 light_direction;
uniform mat4 light_matrix;
uniform float bias;
in vec3 v_normal;
in vec3 v_world;
in vec2 v_uv;
in vec4 v_color;
flat in float v_id;
layout(location = 0) out vec4 out_albedo;
layout(location = 1) out vec4 out_light;
layout(location = 2) out float out_id;
float visibility(vec3 normal) {
    if (!use_shadow) return 1.0;
    vec4 projected = light_matrix * vec4(v_world + normal * bias * 2.0, 1.0);
    vec3 coords = projected.xyz / projected.w * 0.5 + 0.5;
    if (coords.x <= 0.0 || coords.x >= 1.0 || coords.y <= 0.0 || coords.y >= 1.0 || coords.z >= 1.0) return 1.0;
    vec2 texel = 1.0 / vec2(textureSize(shadow_map, 0));
    float lit = 0.0;
    for (int x = -1; x <= 1; x++)
        for (int y = -1; y <= 1; y++)
            lit += coords.z - bias * 0.002 > texture(shadow_map, coords.xy + vec2(x, y) * texel).r ? 0.0 : 1.0;
    return lit / 9.0;
}
void main() {
    vec4 color = base_color * v_color;
    if (has_texture) color *= texture(color_texture, v_uv);
    if (masked && color.a < cutoff) discard;
    vec3 normal = normalize(v_normal);
    if (!gl_FrontFacing) normal = -normal;
    if (is_floor) {
        out_albedo = vec4(0.0);
        out_light = vec4(0.0, visibility(vec3(0.0, 1.0, 0.0)), gl_FragCoord.z, 1.0);
        out_id = -1.0;
        return;
    }
    float lambert = max(dot(normal, light_direction), 0.0);
    out_albedo = vec4(color.rgb, 1.0);
    out_light = vec4(lambert, lambert > 0.0 ? visibility(normal) : 1.0, gl_FragCoord.z, 1.0);
    out_id = v_id;
}
'''

DEPTH_FRAGMENT = '''
#version 330
void main() {}
'''


def context():
    global _context
    if _context is None:
        import moderngl
        _context = moderngl.create_standalone_context(require=330)
    return _context


def shutdown():
    """Release every GPU object and the context (for long-running hosts and tests).

    Do not call this right before the process exits: objects still referenced
    would touch the released context. main.py skips finalisation instead."""
    global _context
    for model in list(_models):
        model.release()
    if _context is not None:
        try:
            _context.release()
        except Exception:  # already gone
            pass
        _context = None



def available():
    try:
        context()
        return True
    except Exception:  # no OpenGL 3.3 driver
        return False


def look_at(eye, target, up=(0., 1., 0.)):
    forward = np.asarray(target, float) - eye
    forward /= np.linalg.norm(forward) or 1
    right = np.cross(forward, up)
    if np.linalg.norm(right) < 1e-6:
        right = np.cross(forward, (0., 0., 1.))
    right /= np.linalg.norm(right)
    true_up = np.cross(right, forward)
    view = np.eye(4)
    view[0, :3], view[1, :3], view[2, :3] = right, true_up, -forward
    view[:3, 3] = -view[:3, :3] @ eye
    return view


def perspective(fov, aspect, near, far):
    f = 1 / math.tan(math.radians(fov) / 2)
    return np.array([[f / aspect, 0, 0, 0], [0, f, 0, 0],
                     [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)], [0, 0, -1, 0]])


def orthographic(size, near, far):
    return np.array([[1 / size, 0, 0, 0], [0, 1 / size, 0, 0], [0, 0, -2 / (far - near), -(far + near) / (far - near)],
                     [0, 0, 0, 1]])


def gl_matrix(matrix):
    return np.asarray(matrix, np.float32).T.tobytes()


class GPUModel:
    """Model geometry, textures and vertex arrays uploaded once."""

    def __init__(self, model):
        ctx = context()
        self.model = model
        self.program = ctx.program(vertex_shader=VERTEX, fragment_shader=FRAGMENT)
        self.depth_program = ctx.program(vertex_shader=VERTEX, fragment_shader=DEPTH_FRAGMENT)
        self.textures = {}
        for index, image in model.images.items():
            if image is not None:
                texture = ctx.texture((image.shape[1], image.shape[0]), 4, np.ascontiguousarray(image).tobytes())
                texture.build_mipmaps()
                texture.filter = (ctx.LINEAR_MIPMAP_LINEAR, ctx.LINEAR)
                self.textures[index] = texture
        self.parts = []
        self.buffers = []
        for primitive in model.primitives:
            if primitive.skin is not None:
                skin = model.skins[primitive.skin]
                dominant = np.take_along_axis(primitive.joints, primitive.weights.argmax(axis=1)[:, None], 1)[:, 0]
                ids = np.array(skin['joints'], np.float32)[np.clip(dominant, 0, len(skin['joints']) - 1)] + 1
            else:
                ids = np.full(len(primitive.positions), primitive.node + 1, np.float32)
            buffers = [(primitive.positions, '3f', 'in_position'), (primitive.normals, '3f', 'in_normal'),
                       (primitive.uvs, '2f', 'in_uv'), (primitive.colors, '4f', 'in_color'),
                       (primitive.joints, '4i', 'in_joints'), (primitive.weights, '4f', 'in_weights'),
                       (ids[:, None], '1f', 'in_id')]
            vbos = [(ctx.buffer(np.ascontiguousarray(data).tobytes()), fmt, name) for data, fmt, name in buffers]
            index_buffer = ctx.buffer(primitive.indices.astype(np.uint32).tobytes())
            self.buffers += [buffer for buffer, _, _ in vbos] + [index_buffer]
            arrays = []
            for program in (self.program, self.depth_program):
                content = [(buffer, fmt, name) for buffer, fmt, name in vbos if name in program]
                arrays.append(ctx.vertex_array(program, content, index_buffer, index_element_size=4))
            self.parts.append((primitive, arrays[0], arrays[1]))
        floor = np.array([[-1, 0, -1], [1, 0, -1], [1, 0, 1], [-1, 0, 1]], np.float32)
        floor_buffers = [(floor, '3f', 'in_position'), (np.tile([0, 1, 0], (4, 1)).astype(np.float32), '3f', 'in_normal'),
                         (np.zeros((4, 2), np.float32), '2f', 'in_uv'), (np.ones((4, 4), np.float32), '4f', 'in_color'),
                         (np.zeros((4, 4), np.int32), '4i', 'in_joints'), (np.zeros((4, 4), np.float32), '4f', 'in_weights'),
                         (np.zeros((4, 1), np.float32), '1f', 'in_id')]
        self.floor = ctx.vertex_array(self.program, [(ctx.buffer(d.tobytes()), f, n) for d, f, n in floor_buffers],
                                      ctx.buffer(np.array([0, 1, 2, 0, 2, 3], np.uint32).tobytes()), index_element_size=4)
        self.shadow_size = 2048
        self.shadow_texture = ctx.depth_texture((self.shadow_size, self.shadow_size))
        self.shadow_texture.compare_func = ''
        self.shadow_fbo = ctx.framebuffer(depth_attachment=self.shadow_texture)
        self.joint_textures = {}
        self.objects = [self.program, self.depth_program, self.floor, self.shadow_texture, self.shadow_fbo,
                        *self.textures.values(), *self.buffers]
        _models.add(self)

    def release(self):
        for item in self.objects + list(self.joint_textures.values()) + [a for _, c, d in self.parts for a in (c, d)]:
            try:
                item.release()
            except Exception:  # released twice or context lost
                pass
        self.objects, self.parts, self.joint_textures = [], [], {}

    def joints(self, skin_index, world):
        matrices = self.model.joint_matrices(skin_index, world)
        data = np.ascontiguousarray(matrices.transpose(0, 2, 1)).astype(np.float32).tobytes()
        texture = self.joint_textures.get(skin_index)
        if texture is None or texture.width != len(matrices) * 4:
            texture = context().texture((len(matrices) * 4, 1), 4, data, dtype='f4')
            texture.filter = (context().NEAREST, context().NEAREST)
            self.joint_textures[skin_index] = texture
        else:
            texture.write(data)
        return texture

    def draw(self, program_index, world, uniforms):
        for primitive, color_array, depth_array in self.parts:
            array = color_array if program_index == 0 else depth_array
            program = array.program
            skinned = primitive.skin is not None
            if 'skinned' in program:
                program['skinned'].value = skinned
            if skinned:
                self.joints(primitive.skin, world).use(location=1)
                if 'joint_texture' in program:
                    program['joint_texture'].value = 1
            if 'model' in program:
                program['model'].write(gl_matrix(world[primitive.node]))
            if program_index == 0:
                material = self.model.materials[primitive.material] if primitive.material < len(self.model.materials) else self.model.materials[0]
                texture = self.textures.get(material.get('image'))
                program['has_texture'].value = texture is not None and uniforms['textures']
                if texture is not None:
                    texture.use(location=0)
                    program['color_texture'].value = 0
                program['base_color'].value = tuple(material['color']) if uniforms['textures'] else (1., 1., 1., 1.)
                program['masked'].value = material['mask']
                program['cutoff'].value = material['cutoff']
                program['is_floor'].value = False
            array.render()


def bounds(model, world):
    points = []
    for primitive in model.primitives:
        positions = primitive.positions
        if primitive.skin is None:
            matrix = world[primitive.node]
            points.append(positions @ matrix[:3, :3].T + matrix[:3, 3])
        else:
            skin = model.skins[primitive.skin]
            matrices = model.joint_matrices(primitive.skin, world)
            sample = slice(None, None, max(1, len(positions) // 20000))
            joints, weights, local = primitive.joints[sample], primitive.weights[sample], positions[sample]
            blended = np.einsum('vk,vkij->vij', weights, matrices[np.clip(joints, 0, len(skin['joints']) - 1)])
            points.append(np.einsum('vij,vj->vi', blended[:, :3, :3], local) + blended[:, :3, 3])
    points = np.concatenate(points)
    low, high = np.percentile(points, .2, axis=0), np.percentile(points, 99.8, axis=0)
    return low, high


def render(gpu, world, camera, width, height, light_direction, supersample=1, cast_shadows=True, floor=True,
           textures=True, outline='parts', line_width=1.):
    ctx = context()
    ss = max(1, int(supersample))
    w, h = max(8, int(width)) * ss, max(8, int(height)) * ss
    low, high = bounds(gpu.model, world)
    center, radius = (low + high) / 2, float(np.linalg.norm(high - low) / 2) or 1.
    position, forward, _, _ = camera.basis()
    distance = float(np.linalg.norm(position - center))
    near, far = max(radius * .01, distance - radius * 3), distance + radius * 3
    view_projection = perspective(camera.fov, w / h, near, far) @ look_at(position, camera.target)
    light = np.asarray(light_direction, float)
    light_view = look_at(center + light * radius * 3, center)
    light_matrix = orthographic(radius * 1.6, radius * .5, radius * 6) @ light_view
    uniforms = {'textures': textures}
    if cast_shadows:
        gpu.shadow_fbo.use()
        gpu.shadow_fbo.clear(depth=1.)
        ctx.enable(ctx.DEPTH_TEST)
        ctx.disable(ctx.CULL_FACE)
        gpu.depth_program['view_projection'].write(gl_matrix(light_matrix))
        gpu.draw(1, world, uniforms)
    albedo = ctx.texture((w, h), 4)
    lighting = ctx.texture((w, h), 4, dtype='f4')
    ids = ctx.texture((w, h), 1, dtype='f4')
    depth = ctx.depth_renderbuffer((w, h))
    fbo = ctx.framebuffer(color_attachments=[albedo, lighting, ids], depth_attachment=depth)
    fbo.use()
    fbo.clear(0., 0., 0., 0., depth=1.)
    ctx.enable(ctx.DEPTH_TEST)
    program = gpu.program
    program['view_projection'].write(gl_matrix(view_projection))
    program['light_direction'].value = tuple(float(v) for v in light)
    program['light_matrix'].write(gl_matrix(light_matrix))
    program['use_shadow'].value = bool(cast_shadows)
    program['bias'].value = radius * .004
    gpu.shadow_texture.use(location=2)
    program['shadow_map'].value = 2
    gpu.draw(0, world, uniforms)
    if floor:
        floor_matrix = np.diag([radius * 2.4, 1, radius * 2.4, 1.])
        floor_matrix[:3, 3] = (center[0], low[1], center[2])
        program['skinned'].value = False
        program['model'].write(gl_matrix(floor_matrix))
        program['has_texture'].value = False
        program['masked'].value = False
        program['is_floor'].value = True
        gpu.floor.render()
    def read(texture, components, dtype):
        raw = np.frombuffer(texture.read(), dtype).reshape(h, w, components)
        return raw[::-1]
    color = read(albedo, 4, np.uint8).astype(np.float32) / 255
    light_data = read(lighting, 4, np.float32)
    node_ids = read(ids, 1, np.float32)[..., 0]
    for item in (albedo, lighting, ids, depth, fbo):
        item.release()
    body = color[..., 3] > .5
    floor_mask = node_ids < -.5
    darkness = np.where(body, 1 - light_data[..., 0] * light_data[..., 1], 0).astype(np.float32)
    floor_shadow = np.where(floor_mask, 1 - light_data[..., 1], 0).astype(np.float32)
    edges = np.zeros((h, w), bool)
    if outline != 'none':
        depth_values = np.where(body, light_data[..., 2], 1.)
        horizontal = body[:, 1:] != body[:, :-1]
        vertical = body[1:, :] != body[:-1, :]
        if outline == 'parts':
            ndc = depth_values * 2 - 1
            linear = 2 * near * far / np.maximum(far + near - ndc * (far - near), 1e-6)
            jump = np.abs(np.diff(linear, axis=1)) > radius * .08
            horizontal |= jump & body[:, 1:] & body[:, :-1]
            jump = np.abs(np.diff(linear, axis=0)) > radius * .08
            vertical |= jump & body[1:, :] & body[:-1, :]
        edges[:, 1:] |= horizontal
        edges[:, :-1] |= horizontal
        edges[1:, :] |= vertical
        edges[:-1, :] |= vertical
        extra = int(round(line_width * ss)) - 2
        if extra > 0:
            from scipy import ndimage
            edges = ndimage.binary_dilation(edges, iterations=extra)
    from mannequin import _downsample
    coverage = _downsample(body, ss)
    weighted = _downsample(darkness * body, ss)
    albedo_small = np.stack([_downsample(color[..., c] * body, ss) for c in range(3)], -1)
    albedo_small /= np.maximum(coverage, 1e-6)[..., None]
    return {
        'alpha': coverage,
        'darkness': np.where(coverage > 0, weighted / np.maximum(coverage, 1e-6), 0).astype(np.float32),
        'floor': _downsample(floor_shadow, ss),
        'outline': _downsample(edges, ss),
        'albedo': albedo_small.astype(np.float32),
        'ids': (node_ids[ss // 2::ss, ss // 2::ss][:int(height), :int(width)].round().astype(np.int32) - 1),
    }
