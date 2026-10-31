"""Check exported world geometry independently of the export conversion helpers."""
import ast
import io
import json
import math
import re
import struct
import unittest
import zipfile

from modeler import apply_finish, evaluate, tessellate, to_glb, to_usdz
from test_modeler import FakeBrep

try:
    import _smlib_core as native_sm
except ImportError:
    native_sm = None


def rotate_quaternion(v, q):
    x, y, z, w = q
    a, b, c = v
    cross = (y*c-z*b, z*a-x*c, x*b-y*a)
    cross2 = (y*cross[2]-z*cross[1], z*cross[0]-x*cross[2], x*cross[1]-y*cross[0])
    return [v[i] + 2*(w*cross[i] + cross2[i]) for i in range(3)]


def apply_node(v, node, normal=False):
    factors = node.get('scale', [1, 1, 1])
    v = [v[i] / factors[i] if normal else v[i] * factors[i] for i in range(3)]
    v = rotate_quaternion(v, node.get('rotation', [0, 0, 0, 1]))
    return v if normal else [v[i] + node.get('translation', [0, 0, 0])[i] for i in range(3)]


def glb_world(data):
    length = struct.unpack_from('<I', data, 12)[0]
    doc = json.loads(data[20:20+length])
    binary = data[28+length:]
    result = {}

    def vectors(index):
        accessor = doc['accessors'][index]
        view = doc['bufferViews'][accessor['bufferView']]
        values = struct.unpack_from('<' + 'f' * (accessor['count'] * 3), binary,
                                    view.get('byteOffset', 0) + accessor.get('byteOffset', 0))
        return [values[i:i+3] for i in range(0, len(values), 3)]

    def visit(index, parents):
        node = doc['nodes'][index]
        path = [node, *parents]
        if 'mesh' in node:
            primitive = doc['meshes'][node['mesh']]['primitives'][0]
            world = []
            for attr in ('POSITION', 'NORMAL'):
                items = []
                for v in vectors(primitive['attributes'][attr]):
                    for ancestor in path:
                        v = apply_node(v, ancestor, attr == 'NORMAL')
                    # glTF Y-up back to model Z-up.
                    items.extend((v[0], -v[2], v[1]))
                world.append(items)
            result[node['name']] = world
        for child in node.get('children', []):
            visit(child, path)

    for index in doc['scenes'][0]['nodes']:
        visit(index, [])
    return doc, result


def usd_world(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        stage = archive.read('model.usda').decode()
    declarations = list(re.finditer(r'^( *)def (Xform|Mesh) "([^"]+)"', stage, re.M))
    stack, result, paths = [], {}, {}
    for index, declaration in enumerate(declarations):
        indent, kind, name = declaration.groups()
        depth = len(indent)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        end = declarations[index+1].start() if index+1 < len(declarations) else len(stage)
        body = stage[declaration.end():end]
        if kind == 'Xform':
            node = {}
            for op in ('translate', 'rotateXYZ', 'scale'):
                match = re.search(r'xformOp:' + op + r' = (\([^\n]+\))', body)
                if match:
                    node[op] = ast.literal_eval(match.group(1))
            stack.append((depth, name, node))
            continue
        paths[name] = [item[1] for item in stack]
        world = []
        for attr in ('points', 'normals'):
            values = ast.literal_eval(re.search(attr + r' = (\[[^\n]+\])', body).group(1))
            items = []
            for value in values:
                v = list(value)
                for _, _, node in reversed(stack):
                    factors = node.get('scale', (1, 1, 1))
                    v = [v[i] / factors[i] if attr == 'normals' else v[i] * factors[i] for i in range(3)]
                    # USD rotateXYZ: X, then Y, then Z.
                    for axis, degrees in enumerate(node.get('rotateXYZ', (0, 0, 0))):
                        j, k = (axis+1) % 3, (axis+2) % 3
                        c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
                        v[j], v[k] = c*v[j]-s*v[k], s*v[j]+c*v[k]
                    if attr == 'points':
                        v = [v[i] + node.get('translate', (0, 0, 0))[i] for i in range(3)]
                items.extend(v)
            world.append(items)
        result[name] = world
    return paths, result


class ExportHierarchyTests(unittest.TestCase):
    def test_boolean_result_parent_and_pruning(self):
        for op in ('union', 'subtract', 'intersect'):
            for operands, expected in [('a b', ['parent']), ('left right', ['parent']),
                                       ('a spare', ['parent', 'left'])]:
                source = f'''group parent
position 10 20 30
group left
position 2 0 0
box a 0 0 0 4 4 4
box spare 0 0 0 1 1 1
end
group right
position 3 0 0
box b 0 0 0 4 4 4
end
end
{op} result {operands}
'''
                with self.subTest(op=op, operands=operands):
                    objects, _, _ = evaluate(source, 'text', FakeBrep())
                    self.assertEqual([g['name'] for g in objects.group_paths['result']], expected)
                    doc, _ = glb_world(to_glb(tessellate(objects, FakeBrep())))
                    names = {n['name'] for n in doc['nodes']}
                    if operands == 'left right':
                        self.assertEqual(names, {'parent', 'result'})
                    elif operands == 'a b':
                        self.assertEqual(names, {'parent', 'left', 'spare', 'result'})
                    else:
                        self.assertEqual(names, {'parent', 'left', 'result', 'right', 'b'})

    def test_boolean_between_roots_has_no_inherited_transform(self):
        source = ('group a\nposition 10 0 0\nbox x 0 0 0 4 4 4\nend\n'
                  'group b\nposition 12 0 0\nbox y 0 0 0 4 4 4\nend\n'
                  'subtract result a b')
        objects, _, _ = evaluate(source, 'text', FakeBrep())
        self.assertEqual(objects.group_paths['result'], [])
        self.assertNotIn('result', objects.top_groups)
        doc, _ = glb_world(to_glb(tessellate(objects, FakeBrep())))
        self.assertEqual([n['name'] for n in doc['nodes']], ['result'])

    def test_part_instances_keep_distinct_group_paths(self):
        source = ('part p\ngroup detail\nposition 2 3 4\nbox body 0 0 0 1 1 1\nend\nend\n'
                  'group outer\nposition 10 0 0\nuse p first\nuse p second\nend')
        objects, _, _ = evaluate(source, 'text', FakeBrep())
        for instance in ('first', 'second'):
            self.assertEqual([g['name'] for g in objects.group_paths[f'{instance}__body']],
                             ['outer', f'{instance}__detail'])
        doc, _ = glb_world(to_glb(tessellate(objects, FakeBrep())))
        self.assertEqual(len([n for n in doc['nodes'] if 'children' in n]), 3)

    def test_part_group_name_collision_does_not_drop_a_mesh(self):
        source = ('part p\ngroup detail\nbox body 0 0 0 1 1 1\nend\nend\n'
                  'use p first\nbox first__detail 2 0 0 1 1 1')
        objects, _, _ = evaluate(source, 'text', FakeBrep())
        meshes = tessellate(objects, FakeBrep())
        doc, world = glb_world(to_glb(meshes))
        self.assertEqual(set(world), {'first__body', 'first__detail'})
        self.assertEqual(len(doc['meshes']), 2)
        with zipfile.ZipFile(io.BytesIO(to_usdz(meshes))) as archive:
            stage = archive.read('model.usda').decode()
        self.assertEqual(stage.count('def Mesh '), 2)
        self.assertIn('def Xform "first__detail"', stage)
        self.assertIn('def Mesh "first__detail__mesh"', stage)
        self.assertIn('displayName = "first__detail"', stage)

    @unittest.skipIf(native_sm is None, '_smlib_core unavailable')
    def test_native_world_positions_and_normals_survive_both_exports(self):
        source = '''group assembly
scale 2 0.7 1.5
euler 23 37 -19
position 10 -7 3
group detail
scale 0.8 1.7 1.2
euler -31 11 42
position -2 4 6
box body 1 2 3 4 5 6
end
sphere ball 0 0 0 1
end'''
        boolean_source = '''group assembly
scale 2 0.7 1.5
euler 23 37 -19
position 10 -7 3
group left
position 1 0 0
box a 0 0 0 4 4 4
end
group right
position 2 1 1
box b 0 0 0 4 4 4
end
end
subtract result a b'''
        # Defining detail separately and moving it must preserve the same
        # nested transforms through both exporters, including nonuniform scale.
        referenced = '''group detail
scale 0.8 1.7 1.2
euler -31 11 42
position -2 4 6
box body 1 2 3 4 5 6
end
group assembly
scale 2 0.7 1.5
euler 23 37 -19
position 10 -7 3
include detail
sphere ball 0 0 0 1
end'''
        cases = [(source, 'none'), (source, 'fillet'), (referenced, 'none')]
        for op in ('union', 'subtract', 'intersect'):
            closed = boolean_source.replace('subtract result a b', f'{op} result left right')
            opened = closed.replace(f'end\n{op} result', f'{op} result') + '\nend'
            cases.extend(((closed, 'none'), (opened, 'none')))
        for text, finish in cases:
            if finish == 'fillet':
                text = text.replace('sphere ball 0 0 0 1\n', '')
            objects, materials, _ = evaluate(text, 'text', native_sm)
            apply_finish(objects, native_sm, finish, 0.1)
            meshes = tessellate(objects, native_sm, materials=materials)
            for scale in (1, 0.001):
                _, glb = glb_world(to_glb(meshes, scale))
                paths, usd = usd_world(to_usdz(meshes, scale))
                for mesh in meshes:
                    self.assertEqual(paths[mesh['name']],
                                     ['Model', 'Geometry', *[g['name'] for g in mesh['groupPath']]])
                    for output in (glb, usd):
                        positions, normals = output[mesh['name']]
                        for expected, actual in zip(mesh['positions'], positions, strict=True):
                            self.assertAlmostEqual(actual, expected*scale, delta=2e-5*scale)
                        for i in range(0, len(normals), 3):
                            normal = normals[i:i+3]
                            length = math.hypot(*normal)
                            for axis in range(3):
                                self.assertAlmostEqual(normal[axis]/length, mesh['normals'][i+axis], delta=2e-6)


if __name__ == '__main__':
    unittest.main()
