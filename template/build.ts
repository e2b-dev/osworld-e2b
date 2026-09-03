import { Template, defaultBuildLogger } from 'e2b'
import { template } from './template.js'
import { mkdirSync, writeFileSync } from 'node:fs'

const TAG = process.env.GNOME_TAG || 'osworld-gnome'

async function main() {
  console.log(`Building template "${TAG}"...`)
  // 4 vCPU matches OSWorld's reference t3.xlarge. 8 GB (reference has 16) is
  // needed headroom: chrome_open_tabs configs load 3 heavy sites at once and
  // at 4 GB the guest thrashes, leaving CDP unresponsive for minutes.
  const info = await Template.build(template, TAG, {
    cpuCount: parseInt(process.env.CPU_COUNT || '4', 10),
    memoryMB: parseInt(process.env.MEM_MB || '8192', 10),
    skipCache: process.env.SKIP_CACHE === '1',
    onBuildLogs: defaultBuildLogger(),
  })
  const immutableRef = `${info.name}:${info.buildId}`
  mkdirSync('results', { recursive: true })
  writeFileSync('results/template-build.json', JSON.stringify({
    builtAt: new Date().toISOString(),
    templateName: info.name,
    templateId: info.templateId,
    buildId: info.buildId,
    immutableRef,
    osworldCommit: '7a17d3abc86d524420ea4ec96752f84d245fea74',
    cpuCount: parseInt(process.env.CPU_COUNT || '4', 10),
    memoryMB: parseInt(process.env.MEM_MB || '8192', 10),
  }, null, 2) + '\n')
  console.log('BUILD_DONE', JSON.stringify(info))
  console.log(`Use this exact build for validation: export GUEST_TEMPLATE=${immutableRef}`)
}

main().catch((e) => {
  console.error('BUILD_ERROR', e?.message)
  console.error(e)
  process.exit(1)
})
