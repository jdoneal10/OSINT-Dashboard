/** Dark ECharts theme matching the dashboard tokens in index.css. */
export const PALETTE = [
  '#38bdf8', // sky
  '#f59e0b', // amber
  '#a78bfa', // violet
  '#34d399', // emerald
  '#f43f5e', // rose
  '#fb923c', // orange
  '#94a3b8', // slate
  '#e879f9', // fuchsia
  '#facc15', // yellow
]

const axis = {
  axisLine: { lineStyle: { color: '#243041' } },
  axisTick: { lineStyle: { color: '#243041' } },
  axisLabel: { color: '#a7b3c2', fontSize: 11 },
  splitLine: { lineStyle: { color: '#18202b' } },
}

export const THEME = {
  color: PALETTE,
  backgroundColor: 'transparent',
  textStyle: { color: '#a7b3c2', fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif' },
  legend: { textStyle: { color: '#a7b3c2', fontSize: 11 }, icon: 'roundRect' },
  tooltip: {
    backgroundColor: '#18202b',
    borderColor: '#243041',
    textStyle: { color: '#e6ebf1', fontSize: 12 },
  },
  categoryAxis: axis,
  valueAxis: axis,
}
