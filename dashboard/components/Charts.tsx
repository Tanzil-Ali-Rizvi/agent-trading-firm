"use client";

import { useEffect, useRef } from "react";
import { createChart, ColorType, CrosshairMode, type IChartApi, type UTCTimestamp } from "lightweight-charts";
import type { Chart as ChartData, Position } from "@/lib/data";

const base = {
  layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#b9b6d6", fontFamily: "Archivo, system-ui, sans-serif", fontSize: 12 },
  grid: { vertLines: { color: "rgba(140,135,245,0.07)" }, horzLines: { color: "rgba(140,135,245,0.07)" } },
  rightPriceScale: { borderColor: "rgba(140,135,245,0.18)" },
  timeScale: { borderColor: "rgba(140,135,245,0.18)", timeVisible: true },
  crosshair: { mode: CrosshairMode.Normal },
  autoSize: true,
  localization: { locale: "en-US" }, // never trust navigator.language: an odd system locale throws inside the chart
};

function useChart(build: (chart: IChartApi) => void, deps: unknown[]) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, base);
    build(chart);
    chart.timeScale().fitContent();
    return () => chart.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return ref;
}

export function CandleChart({ data, position }: { data: ChartData; position?: Position }) {
  const ref = useChart((chart) => {
    const candles = chart.addCandlestickSeries({
      upColor: "#4cc38a", downColor: "#e5636b", borderVisible: false, wickUpColor: "#4cc38a", wickDownColor: "#e5636b",
    });
    candles.setData(data.bars.map(([t, o, h, l, c]) => ({ time: t as UTCTimestamp, open: o, high: h, low: l, close: c })));
    const line = (vals: (number | null)[], color: string) => {
      const s = chart.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      s.setData(data.bars.flatMap(([t], i) => (vals[i] == null ? [] : [{ time: t as UTCTimestamp, value: vals[i] as number }])));
    };
    line(data.ema50, "#f2b35b");
    line(data.ema200, "#8c87f5");
    const vol = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(data.bars.map(([t, o, , , c, v]) => ({ time: t as UTCTimestamp, value: v, color: c >= o ? "rgba(76,195,138,.35)" : "rgba(229,99,107,.35)" })));
    if (position) {
      candles.createPriceLine({ price: position.entry_price, color: "#ede6d6", lineWidth: 1, lineStyle: 2, title: "entry" });
      candles.createPriceLine({ price: position.stop, color: "#e5636b", lineWidth: 1, lineStyle: 2, title: "stop" });
      candles.createPriceLine({ price: position.target, color: "#4cc38a", lineWidth: 1, lineStyle: 2, title: "target" });
    }
  }, [data, position]);
  return <div ref={ref} className="chart" role="img" aria-label={`${data.coin} 4-hour candles with EMA50 and EMA200`} />;
}

export interface LineSet { name: string; color: string; points: [string, number][]; width?: 1 | 2 | 3 }

export function LineCompare({ sets, small = false, normalise = false, label }: { sets: LineSet[]; small?: boolean; normalise?: boolean; label: string }) {
  const ref = useChart((chart) => {
    for (const s of sets) {
      if (!s.points.length) continue;
      const first = s.points[0][1];
      const series = chart.addLineSeries({ color: s.color, lineWidth: s.width ?? 2, priceLineVisible: false, lastValueVisible: !normalise });
      series.setData(
        s.points.map(([t, v]) => ({
          time: (Math.floor(new Date(t.length <= 10 ? `${t}T00:00:00Z` : t).getTime() / 1000)) as UTCTimestamp,
          value: normalise ? (v / first) * 100 : v,
        })),
      );
    }
  }, [sets, normalise]);
  return <div ref={ref} className={small ? "chart small" : "chart"} role="img" aria-label={label} />;
}
