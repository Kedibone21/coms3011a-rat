import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import type { MetricRow } from "../types";
import Chart, { chartPalette } from "./Chart";
import { fmtInt } from "../format";

export default function Overview({
  rows,
  commitCount,
}: {
  rows: MetricRow[];
  commitCount: number;
}) {
  const repoAll = useMemo(
    () => rows.find((r) => r.author === "ALL" && r.object_type === "repository"),
    [rows],
  );
  const fileRows = useMemo(
    () => rows.filter((r) => r.author === "ALL" && r.object_type === "file"),
    [rows],
  );
  const dirRows = useMemo(
    () => rows.filter((r) => r.author === "ALL" && r.object_type === "directory"),
    [rows],
  );
  const authorRows = useMemo(
    () => rows.filter((r) => r.author !== "ALL" && r.object_type === "repository"),
    [rows],
  );

  const topFiles = useMemo(
    () => [...fileRows].sort((a, b) => b.churn - a.churn).slice(0, 10),
    [fileRows],
  );
  const topDirs = useMemo(
    () => [...dirRows].sort((a, b) => b.churn - a.churn).slice(0, 10),
    [dirRows],
  );

  function churnBar(items: MetricRow[], color: string): EChartsOption {
    const ordered = [...items].reverse();
    return {
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (p: unknown) => {
          const item = (p as { name: string; value: number }[])[0];
          return `${item.name}<br/><b>${fmtInt(item.value)}</b> lines churned`;
        },
      },
      grid: { left: 8, right: 40, top: 10, bottom: 10, containLabel: true },
      xAxis: { type: "value", splitLine: { lineStyle: { color: "#26303e" } } },
      yAxis: {
        type: "category",
        data: ordered.map((r) => r.path),
        axisLabel: { fontSize: 10, width: 200, overflow: "truncate" },
      },
      series: [
        {
          type: "bar",
          data: ordered.map((r) => r.churn),
          itemStyle: { color, borderRadius: [0, 3, 3, 0] },
          barMaxWidth: 14,
          label: {
            show: true,
            position: "right",
            fontSize: 10,
            color: "#8ea0b5",
            formatter: (p) => fmtInt(Number(p.value)),
          },
        },
      ],
    };
  }

  const authorPie: EChartsOption = {
    tooltip: { trigger: "item", formatter: "{b}<br/>{c} churn ({d}%)" },
    color: chartPalette,
    series: [
      {
        type: "pie",
        radius: ["35%", "70%"],
        data: authorRows.map((a) => ({ name: a.author, value: a.churn })),
        label: { fontSize: 11, color: "#c7d2de" },
        itemStyle: { borderColor: "#151b24", borderWidth: 2 },
      },
    ],
  };

  return (
    <div className="overview">
      <div className="cards">
        <div className="card">
          <span className="card-label">Commits in set</span>
          <span className="card-value">{fmtInt(commitCount)}</span>
        </div>
        <div className="card">
          <span className="card-label">Files</span>
          <span className="card-value">{fmtInt(fileRows.length)}</span>
        </div>
        <div className="card">
          <span className="card-label">Directories</span>
          <span className="card-value">{fmtInt(dirRows.length)}</span>
        </div>
        <div className="card">
          <span className="card-label">Lines added</span>
          <span className="card-value">{repoAll ? fmtInt(repoAll.added) : "–"}</span>
        </div>
        <div className="card">
          <span className="card-label">Lines removed</span>
          <span className="card-value">{repoAll ? fmtInt(repoAll.removed) : "–"}</span>
        </div>
        <div className="card">
          <span className="card-label">Net growth</span>
          <span className="card-value">
            {repoAll ? (repoAll.growth > 0 ? "+" : "") + fmtInt(repoAll.growth) : "–"}
          </span>
        </div>
        <div className="card">
          <span className="card-label">Total churn</span>
          <span className="card-value">{repoAll ? fmtInt(repoAll.churn) : "–"}</span>
        </div>
      </div>

      {rows.length === 0 ? (
        <p className="muted pad">No metrics for this commit set (empty set).</p>
      ) : (
        <div className="charts">
          <div className="panel">
            <h3>Top files by churn</h3>
            <Chart option={churnBar(topFiles, chartPalette[0])} height={300} />
          </div>
          <div className="panel">
            <h3>Top directories by churn</h3>
            <Chart option={churnBar(topDirs, chartPalette[1])} height={300} />
          </div>
          <div className="panel">
            <h3>Churn by author (repository scope)</h3>
            {authorRows.length > 0 ? (
              <Chart option={authorPie} height={300} />
            ) : (
              <p className="muted pad">No per-author rows.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
