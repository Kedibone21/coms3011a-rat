import { useEffect, useRef } from "react";
import * as echarts from "echarts";

export default function Chart({
  option,
  height = 280,
}: {
  option: echarts.EChartsOption;
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    inst.current = echarts.init(ref.current);
    const onResize = () => inst.current?.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      inst.current?.dispose();
      inst.current = null;
    };
  }, []);

  useEffect(() => {
    inst.current?.setOption(option, true);
  }, [option]);

  return <div ref={ref} style={{ height, width: "100%" }} />;
}

export const chartPalette = [
  "#4f8ff7",
  "#31c48d",
  "#f6a723",
  "#e5484d",
  "#9b6ef3",
  "#22b8cf",
  "#f06595",
  "#94a3b8",
];
