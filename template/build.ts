import { Template, defaultBuildLogger } from 'e2b'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  buildResourcesFromEnvironment,
  computeRecipeIdentity,
  createBuildReceipt,
  loadBuildInputs,
} from './identity.js'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')

async function main() {
  const resources = buildResourcesFromEnvironment(process.env)
  const inputs = loadBuildInputs(root)
  const identity = await computeRecipeIdentity(root, resources)
  const { template } = await import('./template.js')
  console.log(`Building recipe ${identity.digest} as Template "${identity.name}"...`)
  // 4 vCPU matches OSWorld's reference t3.xlarge. 8 GB (reference has 16) is
  // needed headroom: chrome_open_tabs configs load 3 heavy sites at once and
  // at 4 GB the guest thrashes, leaving CDP unresponsive for minutes.
  const info = await Template.build(template, identity.name, {
    cpuCount: resources.cpuCount,
    memoryMB: resources.memoryMB,
    skipCache: process.env.SKIP_CACHE === '1',
    onBuildLogs: defaultBuildLogger(),
  })
  const receipt = createBuildReceipt(identity, inputs, info, new Date().toISOString())
  mkdirSync('results', { recursive: true })
  writeFileSync('results/template-build.json', `${JSON.stringify(receipt, null, 2)}\n`)
  console.log('BUILD_DONE', JSON.stringify(info))
  console.log(
    `Use this exact build for validation: export GUEST_TEMPLATE=${receipt.immutableRef}`,
  )
}

main().catch((e) => {
  console.error('BUILD_ERROR', e?.message)
  console.error(e)
  process.exit(1)
})
