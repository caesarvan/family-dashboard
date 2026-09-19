import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { dependencyIds, dependencyInfo, dependencyCreatesCycle, dependencyPayload, unavailableDependencyIds, dependencyStates } from '../src/lib/taskDependencies.ts';

const row = (id, patch = {}) => ({ id, revision: 1, title: '事项 ' + id, owner: 'shared', done: false, ...patch });
test('old tasks remain available while malformed and missing dependency state stays blocked', () => {
  assert.deepEqual(dependencyIds({}), []);
  assert.equal(dependencyInfo(row('b'), []).blocked, false);
  for (const dependsOn of [null, false, 'a', ['a', 'a'], [''], Array(21).fill('a')]) {
    assert.throws(() => dependencyIds({ dependsOn }));
    assert.equal(dependencyInfo(row('b', { dependsOn }), []).blocked, true);
  }
  assert.equal(dependencyInfo(row('b', { dependsOn: ['missing'] }), []).blocked, true);
});
test('completion follows current predecessors and reopening never rewrites completed history', () => {
  const task = row('b', { dependsOn: ['a'] });
  assert.equal(dependencyInfo(task, [row('a')]).blocked, true);
  assert.equal(dependencyInfo(task, [row('a', { done: true })]).blocked, false);
  assert.equal(dependencyInfo({ ...task, done: true }, [row('a')]).blocked, false);
  assert.equal(dependencyInfo({ ...task, dependencyStatus: 'blocked' }, [row('a', { done: true })]).blocked, true);
  const tasks = [row('a'), task];
  const states = dependencyStates(tasks); for (const item of tasks) assert.deepEqual(states.get(item.id), dependencyInfo(item, tasks));
});
test('selection rejects direct and transitive cycles, lost tasks and cloud mirrors', () => {
  const tasks = [row('a'), row('b', { dependsOn: ['a'] }), row('c', { dependsOn: ['b'] }), row('cloud', { sync: { provider: 'microsoft' } })];
  assert.equal(dependencyCreatesCycle('a', 'c', tasks), true);
  assert.equal(dependencyCreatesCycle('c', 'a', tasks), false);
  assert.deepEqual([...unavailableDependencyIds('a', tasks)].sort(), ['a', 'b', 'c']);
  for (const ids of [['a'], ['c'], ['missing'], ['cloud']]) assert.throws(() => dependencyPayload(ids, tasks, 'a'));
  const ids = ['a']; assert.deepEqual(dependencyPayload(ids, tasks, 'c'), ['a']); assert.deepEqual(ids, ['a']);
  assert.deepEqual(dependencyPayload([], tasks, 'a'), []);
});

// Real editor, dependency fields and SelectionRow handlers. Paper/native hosts
// and transport are synthetic: this is not browser or database acceptance.
function editor(options = {}) {
  const ts = createRequire(import.meta.url)('typescript');
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
  const calls = [], instances = new Map(), effects = [], modules = new Map();
  let holder, cursor = 0, dirty = true, tree, dismissed = 0;
  const React = {
    createElement(type, props, ...children) { return { type, props: { ...props, children: children.flat(Infinity).filter(x => x !== false && x != null) } }; },
    Fragment: 'Fragment',
    useState(initial) { const h = holder, i = cursor++; if (!(i in h)) h[i] = typeof initial === 'function' ? initial() : initial; return [h[i], value => { h[i] = typeof value === 'function' ? value(h[i]) : value; dirty = true; }]; },
    useRef(value) { const i = cursor++; return holder[i] ||= { current: value }; },
    useEffect(fn, deps) { const i = cursor++; if (!holder[i]) { holder[i] = deps; effects.push(fn); } },
  };
  class ApiError extends Error { constructor(message, status) { super(message); this.status = status; } }
  const state = { tasks: options.tasks || [row('a'), row('b')], people: [], sync: options.sync || {} };
  const household = { state, refresh: async () => {}, setNotice() {}, mutate: async (path, method, body) => {
    calls.push({ path, method, body }); if (options.failure !== undefined) throw new ApiError(options.message || '前置事项尚未完成', options.failure); return {};
  } };
  const paper = Object.fromEntries(['Button', 'Text', 'TextInput', 'HelperText', 'IconButton', 'Portal', 'Image', 'Icon', 'TouchableRipple'].map(name => [name, name]));
  paper.Dialog = { Title: 'DialogTitle', ScrollArea: 'DialogScroll', Actions: 'DialogActions' };
  paper.List = { Accordion: 'Accordion', Icon: 'ListIcon' }; paper.Menu = { Item: 'MenuItem' }; paper.Checkbox = { Item: 'CheckboxItem' };
  paper.SegmentedButtons = 'SegmentedButtons'; paper.useTheme = () => ({ colors: {} });
  const mocks = { react: React, 'react-native': { View: 'View', Image: 'Image', ScrollView: 'ScrollView', Platform: { OS: 'web' }, StyleSheet: { create: value => value } },
    'react-native-paper': paper, 'expo-image-picker': {}, 'expo-image-manipulator': {}, '../lib/household': { useHousehold: () => household }, '../lib/api': { ApiError } };
  function load(file) {
    if (!existsSync(file)) file += existsSync(file + '.ts') ? '.ts' : '.tsx';
    if (modules.has(file)) return modules.get(file);
    const exports = {}; modules.set(file, exports);
    const code = ts.transpileModule(readFileSync(file, 'utf8'), { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
    runInNewContext(code, { exports, require: name => mocks[name] || load(resolve(dirname(file), name)), Date, Intl, Error }); return exports;
  }
  const ItemEditor = load(resolve(root, 'ui/ItemEditor.tsx')).default;
  function expand(node, path = 'root') {
    if (node == null || node === false || typeof node !== 'object') return node;
    if (Array.isArray(node)) return node.map((child, i) => expand(child, path + i));
    if (typeof node.type === 'function') {
      const key = path + node.type.name; if (!instances.has(key)) instances.set(key, []);
      const previous = holder, old = cursor; holder = instances.get(key); cursor = 0;
      const result = node.type(node.props); holder = previous; cursor = old; return expand(result, key);
    }
    return { ...node, props: { ...node.props, anchor: expand(node.props.anchor, path + '.anchor'), children: node.props.children.map((child, i) => expand(child, path + '.' + (child?.props?.key ?? i))) } };
  }
  async function flush() { for (let i = 0; i < 12; i++) { if (dirty) { dirty = false; tree = expand(React.createElement(ItemEditor, { kind: 'tasks', item: options.item, onDismiss() { dismissed++; } })); while (effects.length) effects.shift()(); } await new Promise(setImmediate); } assert(!dirty); }
  const nodes = node => !node || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(nodes) : [node, ...nodes(node.props.anchor), ...nodes(node.props.children)];
  const text = node => node == null || node === false ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(text).join(' ') : text(node.props.children);
  function find(label) { const found = nodes(tree).filter(node => (node.props.accessibilityLabel || node.props.label || text(node.props.children)) === label && (node.props.onPress || node.props.onChangeText)); assert.equal(found.length, 1, label); return found[0].props; }
  return { flush, calls, find, text: () => text(tree), state, dismissed: () => dismissed,
    async click(label) { const control = find(label); assert(!control.disabled, label); control.onPress(); await flush(); },
    async input(label, value) { const control = find(label); assert(!control.disabled, label); control.onChangeText(value); await flush(); } };
}

test('real editor chooses a predecessor and saves the explicit original ID with local destination', async () => {
  const h = editor(); await h.flush(); await h.input('名称', '预约后再购买'); await h.click('选择前置事项：事项 a');
  assert.equal(h.find('取消前置事项：事项 a')['aria-checked'], true); assert.equal(h.find('已完成').disabled, true);
  await h.click('保存'); assert.equal(h.calls.length, 1); assert.deepEqual([...h.calls[0].body.dependsOn], ['a']); assert.equal(h.calls[0].body.sourceId, '');
});
test('explicitly clearing dependencies permits completion, without editing predecessors', async () => {
  const h = editor({ item: row('b', { dependsOn: ['a'] }) }); await h.flush(); assert.equal(h.find('已完成').disabled, true);
  await h.click('清空前置事项'); await h.click('已完成'); await h.click('保存');
  assert.deepEqual([...h.calls[0].body.dependsOn], []); assert.equal(h.calls[0].body.done, true); assert.equal(h.calls[0].body.revision, 1); assert.equal(h.state.tasks[0].done, false);
});
test('lost predecessor remains visible until explicit removal and cannot be silently saved away', async () => {
  const h = editor({ item: row('b', { dependsOn: ['lost'] }) }); await h.flush(); await h.click('保存');
  assert.equal(h.calls.length, 0); assert.match(h.text(), /前置事项已失效/);
  await h.click('取消前置事项：已失效的前置事项'); await h.click('保存'); assert.deepEqual([...h.calls[0].body.dependsOn], []);
});
test('server rejection preserves draft and explains the actual predecessor conflict', async () => {
  const h = editor({ item: row('b', { dependsOn: ['a'] }), tasks: [row('a', { done: true }), row('b')], failure: 409 });
  await h.flush(); await h.input('名称', '保留本人草稿'); await h.click('已完成'); await h.click('保存');
  assert.equal(h.find('名称').value, '保留本人草稿'); assert.match(h.text(), /前置事项尚未完成/); assert.equal(h.dismissed(), 0);
});
test('unknown save freezes dependency controls and does not issue a second write', async () => {
  const failing = editor({ item: row('b', { dependsOn: ['a'] }), failure: 0 }); await failing.flush(); await failing.click('保存');
  assert.equal(failing.find('取消前置事项：事项 a').disabled, true); assert.equal(failing.find('保存').disabled, true); assert.equal(failing.calls.length, 1);
  assert.match(failing.text(), /核对后再操作/);
});
test('malformed existing dependencies require explicit reset before any mutation', async () => {
  const h = editor({ item: row('b', { dependsOn: null }) }); await h.flush(); await h.click('保存'); assert.equal(h.calls.length, 0);
  await h.click('清空并重新选择前置事项'); await h.click('保存'); assert.deepEqual([...h.calls[0].body.dependsOn], []);
});
test('new cloud destination keeps dependency controls unavailable with an honest explanation', async () => {
  const h = editor({ sync: { taskSources: [{ id: 'cloud1', name: '微软主清单', writable: true }], primaryTaskSource: { id: 'cloud1' } } });
  await h.flush(); assert.match(h.text(), /同步清单暂不支持前置事项/);
  await h.input('名称', '云端事项'); await h.click('保存'); assert.deepEqual([...h.calls[0].body.dependsOn], []); assert.equal(h.calls[0].body.sourceId, 'cloud1');
});
