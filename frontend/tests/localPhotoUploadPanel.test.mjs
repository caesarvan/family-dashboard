import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
const ts = createRequire(import.meta.url)('typescript'), root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');

// Real TSX, SelectionRow and browser file-input adapter. Native picker/React
// surfaces are synthetic; real browser and API integration remain separate.
function harness() {
  let index = 0, values = [], effects = [], tree, mounted = [], listeners = [], input;
  const calls = [], controller = { view: { selected: [], detail: null, busy: false, needsCheck: false, message: '', unavailable: false, uploading: '' },
    subscribe(fn) { listeners.push(fn); return () => {}; },
    select: async files => calls.push(['select', files]), upload: async () => calls.push(['upload']), check: async () => calls.push(['check']), finish: async () => calls.push(['finish']), reset: () => calls.push(['reset']) };
  const react = { createElement(type, props, ...children) { return { type, props: { ...props, children: children.flat(Infinity) } }; },
    useState(initial) { const i = index++; if (!(i in values)) values[i] = initial; return [values[i], value => { values[i] = typeof value === 'function' ? value(values[i]) : value; }]; },
    useEffect(fn, deps) { const i = index++; if (!(i in values)) { values[i] = deps; effects.push(fn); } } };
  const document = { createElement(kind) { assert.equal(kind, 'input'); const events = {};
    input = { style: {}, files: [], setAttribute() {}, addEventListener(name, callback) { events[name] = callback; }, click() { calls.push(['picker']); }, remove() { mounted = mounted.filter(item => item !== input); }, fire(name) { events[name]?.(); } }; return input; },
    body: { appendChild(value) { mounted.push(value); } } };
  const mocks = { react, 'react-native': { Platform: { OS: 'web' }, StyleSheet: { create: value => value }, View: 'View' },
    'react-native-paper': { Button: 'Button', Text: 'Text', TouchableRipple: 'TouchableRipple', Icon: 'Icon', useTheme: () => ({ colors: {} }) } };
  const cache = new Map();
  function load(path) {
    path = resolve(path); if (!existsSync(path)) path += existsSync(path + '.ts') ? '.ts' : '.tsx';
    if (cache.has(path)) return cache.get(path); const exports = {}; cache.set(path, exports);
    const js = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true } }).outputText;
    runInNewContext(js, { exports, require: name => name in mocks ? mocks[name] : load(resolve(dirname(path), name)), document, Error, TextEncoder }); return exports;
  }
  const Panel = load(root + '/components/LocalPhotoImportPanel.tsx').default;
  function expand(node) {
    if (node == null || typeof node !== 'object') return node;
    if (Array.isArray(node)) return node.map(expand);
    if (typeof node.type === 'function') return expand(node.type(node.props));
    return { ...node, props: { ...node.props, children: (node.props.children || []).map(expand) } };
  }
  function render(disabled = false) { index = 0; tree = expand(Panel({ controller, disabled })); effects.splice(0).forEach(fn => fn()); return tree; }
  function walk(node = tree) { return !node || typeof node !== 'object' ? [] : [node, ...(node.props?.children || []).flatMap(walk)]; }
  const text = node => typeof node === 'string' ? node : (node?.props?.children || []).map(text).join('');
  const button = label => walk().find(node => node.type === 'Button' && text(node) === label);
  const checkbox = () => walk().find(node => node.props.accessibilityRole === 'checkbox');
  return { calls, controller, render, walk, button, checkbox, get input() { return input; }, get mounted() { return mounted; },
    set(patch) { controller.view = { ...controller.view, ...patch }; listeners.forEach(fn => fn()); render(); } };
}

test('device picker opens in gesture, accepts only intended MIME and cancellation does not upload', async () => {
  const h = harness(); h.render(); h.button('从设备选择照片').props.onPress(); assert.equal(h.mounted.length, 1);
  assert.equal(h.input.accept, 'image/jpeg,image/png,image/webp'); assert.equal(h.input.multiple, true);
  h.input.fire('cancel'); await Promise.resolve(); assert.equal(h.mounted.length, 0);
  assert.deepEqual(h.calls.map(c => c[0]), ['picker', 'select']); assert.equal(h.calls[1][1].length, 0);
});
test('selection alone does not upload; explicit accessible consent enables upload', () => {
  const h = harness(); h.render(); h.set({ selected: [{ clientFileId: 'original', filename: '合成.jpg', bytes: 1024 }] });
  assert.equal(h.button('上传并生成预览').props.disabled, true);
  assert.equal(h.checkbox().props.accessibilityState.checked, false); h.checkbox().props.onPress(); h.render();
  assert.equal(h.checkbox().props.accessibilityState.checked, true); assert.equal(h.button('上传并生成预览').props.disabled, false);
  h.button('上传并生成预览').props.onPress(); assert.deepEqual(h.calls, [['upload']]);
});
test('unknown result exposes checking only; no upload/finish path or replacement selection', () => {
  const h = harness(); h.render(); h.set({ selected: [{ clientFileId: 'original', filename: '合成.jpg', bytes: 1024 }], needsCheck: true });
  assert.equal(h.button('从设备选择照片').props.disabled, true); assert.equal(h.button('上传并生成预览'), undefined);
  h.button('核对本次上传').props.onPress(); assert.deepEqual(h.calls, [['check']]);
});
test('staging without original Files offers an explicit finish action; busy disables changes', () => {
  const h = harness(); h.render(); h.set({ detail: { import: { state: 'staging' }, upload: { files: [], canUpload: true } } });
  h.button('结束本批并核对成功项').props.onPress(); assert.deepEqual(h.calls, [['finish']]);
  h.set({ busy: true }); assert.equal(h.button('结束本批并核对成功项').props.disabled, true); assert.equal(h.button('重新选择原文件').props.disabled, true);
  h.set({ busy: false, detail: { import: { state: 'confirmed' }, upload: { files: [], canUpload: false } } });
  assert.equal(h.button('上传并生成预览'), undefined); h.button('选择下一批照片').props.onPress(); assert.deepEqual(h.calls.at(-1), ['reset']);
});
