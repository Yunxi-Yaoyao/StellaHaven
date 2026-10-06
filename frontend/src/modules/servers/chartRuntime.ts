// Only chart families actually used by monitoring pages are registered.
import { use } from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);
export { init, getInstanceByDom } from 'echarts/core';
export type { ECharts, SeriesOption } from 'echarts';
