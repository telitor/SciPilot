import EChartsReactCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);

interface ResultChartProps {
  option: Record<string, unknown>;
}

function ResultChart({ option }: ResultChartProps) {
  return (
    <EChartsReactCore
      echarts={echarts}
      option={option}
      style={{ height: 250 }}
      opts={{ renderer: 'canvas' }}
    />
  );
}

export default ResultChart;
