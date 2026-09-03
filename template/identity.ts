import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { readdir, readFile } from 'node:fs/promises'
import { join, relative, sep } from 'node:path'

export type BuildResources = {
  cpuCount: number
  memoryMB: number
}

export type RecipeIdentity = {
  digest: string
  name: string
  resources: BuildResources
  inputDigests: Record<string, string>
}

export type BuildInputs = {
  schemaVersion: 1
  platform: string
  baseImage: { sourceTag: string; reference: string }
  osworld: { repository: string; commit: string }
  byteReproducible: false
  resolvedDuringBuild: Array<{ name: string; reason: string }>
}

export type BuiltTemplate = {
  name: string
  templateId: string
  buildId: string
}

export type BuildReceipt = {
  schemaVersion: 1
  builtAt: string
  templateName: string
  templateId: string
  buildId: string
  immutableRef: string
  recipeDigest: string
  recipeInputDigests: Record<string, string>
  resources: BuildResources
  baseImage: BuildInputs['baseImage']
  osworld: BuildInputs['osworld']
  byteReproducible: false
  resolvedDuringBuild: BuildInputs['resolvedDuringBuild']
}

export function buildResourcesFromEnvironment(
  environment: NodeJS.ProcessEnv,
): BuildResources {
  const positiveInteger = (name: string, fallback: string): number => {
    const raw = environment[name] ?? fallback
    if (!/^[1-9][0-9]*$/.test(raw)) {
      throw new Error(`${name} must be a positive integer`)
    }
    const value = Number(raw)
    if (!Number.isSafeInteger(value)) {
      throw new Error(`${name} exceeds JavaScript's safe integer range`)
    }
    return value
  }
  return {
    cpuCount: positiveInteger('CPU_COUNT', '4'),
    memoryMB: positiveInteger('MEM_MB', '8192'),
  }
}

const RECIPE_FILES = [
  'package-lock.json',
  'upstream.lock.json',
  'template/build.ts',
  'template/identity.ts',
  'template/inputs.lock.json',
  'template/template.ts',
]

async function filesUnder(root: string): Promise<string[]> {
  const paths: string[] = []
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const path = join(root, entry.name)
    if (entry.isDirectory()) {
      paths.push(...(await filesUnder(path)))
    } else if (entry.isFile()) {
      paths.push(path)
    } else {
      throw new Error(`unsupported recipe input: ${path}`)
    }
  }
  return paths
}

function sha256(value: Buffer | string): string {
  return createHash('sha256').update(value).digest('hex')
}

export async function computeRecipeIdentity(
  root: string,
  resources: BuildResources,
): Promise<RecipeIdentity> {
  const paths = [
    ...RECIPE_FILES.map((path) => join(root, path)),
    ...(await filesUnder(join(root, 'template/files'))),
  ].sort()
  const inputDigests: Record<string, string> = {}
  for (const path of paths) {
    const name = relative(root, path).split(sep).join('/')
    inputDigests[name] = sha256(await readFile(path))
  }
  const digest = sha256(`${JSON.stringify({ schemaVersion: 1, resources, inputDigests })}\n`)
  return {
    digest,
    name: templateNameForRecipe(digest),
    resources: { ...resources },
    inputDigests,
  }
}

export function templateNameForRecipe(digest: string): string {
  if (!/^[0-9a-f]{64}$/.test(digest)) {
    throw new Error('recipe digest must be a lowercase SHA-256 value')
  }
  return `osworld-gnome-${digest.slice(0, 16)}`
}

export function loadBuildInputs(root: string): BuildInputs {
  const parsed: unknown = JSON.parse(
    readFileSync(join(root, 'template/inputs.lock.json'), 'utf8'),
  )
  const upstream: unknown = JSON.parse(readFileSync(join(root, 'upstream.lock.json'), 'utf8'))
  if (typeof parsed !== 'object' || parsed === null) {
    throw new Error('template/inputs.lock.json must contain an object')
  }
  const inputs = parsed as Partial<BuildInputs>
  if (inputs.schemaVersion !== 1 || inputs.platform !== 'linux/amd64') {
    throw new Error('template build inputs must use schema 1 and linux/amd64')
  }
  if (!/^ubuntu@sha256:[0-9a-f]{64}$/.test(inputs.baseImage?.reference ?? '')) {
    throw new Error('template base image must be an immutable Ubuntu digest')
  }
  if (!/^[0-9a-f]{40}$/.test(inputs.osworld?.commit ?? '')) {
    throw new Error('OSWorld source must be locked to a Git commit')
  }
  if (
    typeof upstream !== 'object' ||
    upstream === null ||
    (upstream as { repository?: string }).repository !== inputs.osworld?.repository ||
    (upstream as { commit?: string }).commit !== inputs.osworld?.commit
  ) {
    throw new Error('template OSWorld input must match upstream.lock.json')
  }
  if (inputs.byteReproducible !== false || !Array.isArray(inputs.resolvedDuringBuild)) {
    throw new Error('rolling build inputs must be declared as non-byte-reproducible')
  }
  for (const item of inputs.resolvedDuringBuild) {
    if (!item.name || !item.reason) {
      throw new Error('each rolling build input requires a name and reason')
    }
  }
  return inputs as BuildInputs
}

export function createBuildReceipt(
  identity: RecipeIdentity,
  inputs: BuildInputs,
  info: BuiltTemplate,
  builtAt: string,
): BuildReceipt {
  if (info.name !== identity.name) {
    throw new Error(`E2B built unexpected Template name: ${info.name}`)
  }
  return {
    schemaVersion: 1,
    builtAt,
    templateName: info.name,
    templateId: info.templateId,
    buildId: info.buildId,
    immutableRef: `${info.name}:${info.buildId}`,
    recipeDigest: identity.digest,
    recipeInputDigests: identity.inputDigests,
    resources: identity.resources,
    baseImage: inputs.baseImage,
    osworld: inputs.osworld,
    byteReproducible: inputs.byteReproducible,
    resolvedDuringBuild: inputs.resolvedDuringBuild,
  }
}
