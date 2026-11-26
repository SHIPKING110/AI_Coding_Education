<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([RadarChart, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  items: { name: string; total: number; correct: number; correct_rate: number }[]
  height?: number
}>()

const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function render() {
  if (!el.value) return
  if (!chart) chart = echarts.init(el.value)
  const rows = props.items.slice(0, 8)
  chart.setOption(
    {
      tooltip: {
        trigger: 'item',
        formatter: () =>
          rows
            .map(
              (item) =>
                `${item.name}：${Math.round(item.correct_rate * 100)}%（答对 ${item.correct}/${item.total} 题）`,
            )
            .join('<br/>'),
      },
      radar: {
        indicator: rows.map((item) => ({ name: item.name, max: 100 })),
        radius: '64%',
        splitNumber: 4,
        axisName: { color: '#475569', fontSize: 11 },
        splitArea: { areaStyle: { color: ['#f8fafc', '#f1f5f9'] } },
        splitLine: { lineStyle: { color: '#e2e8f0' } },
        axisLine: { lineStyle: { color: '#e2e8f0' } },
      },
      series: [
        {
          type: 'radar',
          symbolSize: 5,
          lineStyle: { color: '#0f766e', width: 2 },
          itemStyle: { color: '#0f766e' },
          areaStyle: { color: 'rgba(15, 118, 110, 0.18)' },
          data: [
            {
              value: rows.map((item) => Math.round(item.correct_rate * 100)),
              name: '知识点掌握度',
            },
          ],
        },
      ],
    },
    true,
  )
}

function resize() {
  chart?.resize()
}

watch(
  () => props.items,
  () => nextTick(render),
  { deep: true },
)

onMounted(() => {
  nextTick(render)
  window.addEventListener('resize', resize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div v-if="items.length" ref="el" class="ability-radar" :style="{ height: `${height ?? 260}px` }" />
  <p v-else class="radar-empty">完成练习并标注知识点后，这里会生成能力雷达。</p>
</template>

<style scoped>
.ability-radar {
  width: 100%;
}
.radar-empty {
  padding: 24px 12px;
  text-align: center;
  color: var(--ink-3);
  font-size: 12.5px;
}
</style>
