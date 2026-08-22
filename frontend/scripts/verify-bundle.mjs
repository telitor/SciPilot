import { readdir, readFile, stat } from 'node:fs/promises';

const projectRoot = new URL('../', import.meta.url);
const distRoot = new URL('./dist/', projectRoot);
const assetsRoot = new URL('./assets/', distRoot);
const maxChunkBytes = 500_000;

const assetNames = await readdir(assetsRoot);
const javascriptAssets = assetNames.filter((name) => name.endsWith('.js'));

const assetSizes = new Map(
  await Promise.all(
    javascriptAssets.map(async (name) => [
      name,
      (await stat(new URL(name, assetsRoot))).size,
    ]),
  ),
);

const requiredChunkPrefixes = [
  'echarts-core-',
  'echarts-renderer-',
  'echarts-react-',
  'ResultChart-',
];

const missingChunks = requiredChunkPrefixes.filter(
  (prefix) => !javascriptAssets.some((name) => name.startsWith(prefix)),
);

if (missingChunks.length > 0) {
  throw new Error(`Missing expected lazy chart chunks: ${missingChunks.join(', ')}`);
}

const oversizedChunks = [...assetSizes.entries()].filter(([, size]) => size > maxChunkBytes);
if (oversizedChunks.length > 0) {
  const details = oversizedChunks
    .map(([name, size]) => `${name} (${(size / 1_000).toFixed(2)} kB)`)
    .join(', ');
  throw new Error(`JavaScript chunks exceed the 500 kB budget: ${details}`);
}

const entryHtml = await readFile(new URL('./index.html', distRoot), 'utf8');
const deferredChartAssets = javascriptAssets.filter((name) => (
  requiredChunkPrefixes.some((prefix) => name.startsWith(prefix))
));
const eagerlyReferencedChartAssets = deferredChartAssets.filter((name) => entryHtml.includes(name));

if (eagerlyReferencedChartAssets.length > 0) {
  throw new Error(
    `Chart chunks must not be referenced by the initial page: ${eagerlyReferencedChartAssets.join(', ')}`,
  );
}

const measuredChartChunks = deferredChartAssets
  .map((name) => `${name}=${((assetSizes.get(name) || 0) / 1_000).toFixed(2)} kB`)
  .join(', ');

console.log(`Bundle verification passed: ${measuredChartChunks}`);
