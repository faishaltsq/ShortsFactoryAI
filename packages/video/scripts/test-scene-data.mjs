import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import ts from 'typescript';
import vm from 'node:vm';
const module = {exports: {}};
const require = createRequire(import.meta.url);
const source = readFileSync(new URL('../src/scene-data.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText;
vm.runInNewContext(compiled, {module, exports: module.exports, require});
const {validateSceneData, localImage} = module.exports;
const fixture = JSON.parse(readFileSync(new URL('../fixtures/all-templates.json', import.meta.url), 'utf8'));
for (const scene of fixture.scenes) {
  assert.doesNotThrow(() => validateSceneData(scene));
  if (!['KineticTypography', 'EducationalExplainer'].includes(scene.template)) {
    assert.throws(() => validateSceneData({...scene, data: undefined}));
    assert.throws(() => validateSceneData({...scene, data: {...scene.data, arbitrary: 'tsx'}}));
  }
}
for (const src of ['https://example.com/image.png', '../escape.png', '/absolute.png', 'assets/no-hash.png', 'data:image/svg+xml,bad']) {
  assert.throws(() => localImage(src));
}
assert.equal(localImage(`assets/${'a'.repeat(64)}.png`), `assets/${'a'.repeat(64)}.png`);
const graph = fixture.scenes.find(s => s.template === 'InfographicMotion');
assert.throws(() => validateSceneData({...graph, data: {...graph.data, items: [{label: 'bad', value: NaN}]}}));
assert.throws(() => validateSceneData({...graph, data: {...graph.data, maxValue: 1}}));
console.log('PASS template contracts: six valid fixtures, incomplete/unknown/remote/nonfinite rejected');
