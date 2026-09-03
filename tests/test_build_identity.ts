import assert from 'node:assert/strict'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'

import {
  buildResourcesFromEnvironment,
  computeRecipeIdentity,
  createBuildReceipt,
  loadBuildInputs,
  templateNameForRecipe,
} from '../template/identity.js'

async function fixture(root: string) {
  await mkdir(join(root, 'template/files'), { recursive: true })
  await writeFile(join(root, 'package-lock.json'), '{"lockfileVersion":3}\n')
  await writeFile(join(root, 'upstream.lock.json'), '{"commit":"abc"}\n')
  await writeFile(
    join(root, 'template/inputs.lock.json'),
    '{"baseImage":{"reference":"ubuntu@sha256:abc"}}\n',
  )
  await writeFile(join(root, 'template/build.ts'), 'build\n')
  await writeFile(join(root, 'template/identity.ts'), 'identity\n')
  await writeFile(join(root, 'template/template.ts'), 'template\n')
  await writeFile(join(root, 'template/files/a.txt'), 'a\n')
}

test('recipe identity is stable for the same files and resources', async (context) => {
  const root = await mkdtemp(join(tmpdir(), 'osworld-recipe-stable-'))
  context.after(() => rm(root, { recursive: true, force: true }))
  await fixture(root)

  const first = await computeRecipeIdentity(root, { cpuCount: 4, memoryMB: 8192 })
  const second = await computeRecipeIdentity(root, { cpuCount: 4, memoryMB: 8192 })

  assert.deepEqual(first, second)
  assert.match(first.digest, /^[0-9a-f]{64}$/)
  assert.equal(first.name, templateNameForRecipe(first.digest))
})

test('recipe identity changes when a build input or resource changes', async (context) => {
  const root = await mkdtemp(join(tmpdir(), 'osworld-recipe-changes-'))
  context.after(() => rm(root, { recursive: true, force: true }))
  await fixture(root)
  const baseline = await computeRecipeIdentity(root, { cpuCount: 4, memoryMB: 8192 })

  await writeFile(join(root, 'template/files/a.txt'), 'changed\n')
  const fileChanged = await computeRecipeIdentity(root, { cpuCount: 4, memoryMB: 8192 })
  const resourcesChanged = await computeRecipeIdentity(root, { cpuCount: 8, memoryMB: 8192 })

  assert.notEqual(fileChanged.digest, baseline.digest)
  assert.notEqual(resourcesChanged.digest, fileChanged.digest)
})

test('template names are derived from recipe digests', () => {
  assert.equal(
    templateNameForRecipe('0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'),
    'osworld-gnome-0123456789abcdef',
  )
  assert.throws(() => templateNameForRecipe('not-a-digest'), /SHA-256/)
})

test('build resources accept positive integers only', () => {
  assert.deepEqual(buildResourcesFromEnvironment({}), { cpuCount: 4, memoryMB: 8192 })
  assert.deepEqual(buildResourcesFromEnvironment({ CPU_COUNT: '8', MEM_MB: '16384' }), {
    cpuCount: 8,
    memoryMB: 16384,
  })
  assert.throws(() => buildResourcesFromEnvironment({ CPU_COUNT: '4.5' }), /CPU_COUNT/)
  assert.throws(() => buildResourcesFromEnvironment({ MEM_MB: '0' }), /MEM_MB/)
})

test('build inputs require an immutable base image and describe rolling inputs', () => {
  const inputs = loadBuildInputs(process.cwd())

  assert.match(inputs.baseImage.reference, /^ubuntu@sha256:[0-9a-f]{64}$/)
  assert.equal(inputs.byteReproducible, false)
  assert.deepEqual(inputs.resolvedDuringBuild.map(({ name }) => name), [
    'Ubuntu apt packages',
    'Google Chrome stable',
    'VS Code 1.91.1 Debian package',
  ])
})

test('build inputs reject an OSWorld source lock mismatch', async (context) => {
  const root = await mkdtemp(join(tmpdir(), 'osworld-input-mismatch-'))
  context.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, 'template'), { recursive: true })
  await writeFile(
    join(root, 'template/inputs.lock.json'),
    JSON.stringify({
      schemaVersion: 1,
      platform: 'linux/amd64',
      baseImage: {
        sourceTag: 'ubuntu:22.04',
        reference: `ubuntu@sha256:${'a'.repeat(64)}`,
      },
      osworld: {
        repository: 'https://github.com/xlang-ai/OSWorld.git',
        commit: 'a'.repeat(40),
      },
      byteReproducible: false,
      resolvedDuringBuild: [{ name: 'apt', reason: 'rolling repository' }],
    }),
  )
  await writeFile(
    join(root, 'upstream.lock.json'),
    JSON.stringify({
      repository: 'https://github.com/xlang-ai/OSWorld.git',
      commit: 'b'.repeat(40),
    }),
  )

  assert.throws(() => loadBuildInputs(root), /upstream\.lock\.json/)
})

test('build receipts distinguish recipe identity from the immutable E2B artifact', () => {
  const inputs = loadBuildInputs(process.cwd())
  const identity = {
    digest: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
    name: 'osworld-gnome-0123456789abcdef',
    resources: { cpuCount: 4, memoryMB: 8192 },
    inputDigests: { 'package-lock.json': 'a'.repeat(64) },
  }

  const receipt = createBuildReceipt(
    identity,
    inputs,
    { name: identity.name, templateId: 'template-id', buildId: 'build-id' },
    '2026-09-02T12:00:00.000Z',
  )

  assert.deepEqual(receipt, {
    schemaVersion: 1,
    builtAt: '2026-09-02T12:00:00.000Z',
    templateName: 'osworld-gnome-0123456789abcdef',
    templateId: 'template-id',
    buildId: 'build-id',
    immutableRef: 'osworld-gnome-0123456789abcdef:build-id',
    recipeDigest: identity.digest,
    recipeInputDigests: identity.inputDigests,
    resources: identity.resources,
    baseImage: inputs.baseImage,
    osworld: inputs.osworld,
    byteReproducible: false,
    resolvedDuringBuild: inputs.resolvedDuringBuild,
  })
})
