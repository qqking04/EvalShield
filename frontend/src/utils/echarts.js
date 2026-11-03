// ES9-P-16：echarts 按需注册单点导出（设计文档 §6 P-16：禁止整包 import * as echarts from 'echarts'）
// 通过 vite.config.js 的 resolve.alias 将 'echarts' 指向本模块：
// 项目内所有 echarts 触点均经 echarts-for-react 引入（其内部仅使用 init/dispose/getInstanceByDom），
// 页面代码零改动即完成按需化。新增图表类型/组件时必须同步扩充下方 use() 清单，
// 否则图表会静默不渲染（echarts 按需模式的已知坑）。
// 使用面依据（grep 全表）：series=bar/line/pie/radar/heatmap/scatter/gauge；
// 组件=Grid(坐标系)/Tooltip/Legend/Title/DataZoom(CostDashboard)/VisualMap(engineCharts·CoverageHeatmap)/
// MarkLine(engineCharts·Versions·Queue)/Graphic(ProjectQualityView)/Dataset/Radar 坐标系；renderer=canvas。
import * as echarts from 'echarts/core'
import {
  BarChart,
  LineChart,
  PieChart,
  RadarChart,
  HeatmapChart,
  ScatterChart,
  GaugeChart,
} from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DataZoomComponent,
  VisualMapComponent,
  MarkLineComponent,
  GraphicComponent,
  DatasetComponent,
  RadarComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  RadarChart,
  HeatmapChart,
  ScatterChart,
  GaugeChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DataZoomComponent,
  VisualMapComponent,
  MarkLineComponent,
  GraphicComponent,
  DatasetComponent,
  RadarComponent,
  CanvasRenderer,
])

export * from 'echarts/core'
export default echarts
