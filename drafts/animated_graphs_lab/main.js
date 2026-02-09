const years = Array.from({ length: 45 }, (_, i) => 1981 + i);

const hotDays = [
  12, 28, 22, 16, 2, 25, 180, 62, 4, 18,
  123, 36, 31, 112, 39, 24, 45, 55, 18, 9,
  76, 49, 184, 79, 144, 121, 73, 238, 285, 244,
  90, 102, 271, 231, 134, 257, 223, 314, 119, 188,
  61, 296, 239, 205, 232
];

const anomaly = [
  0.20, 0.07, 0.06, -0.44, -0.29, -0.05, 0.62, 0.25, -0.20, -0.11,
  0.35, -0.24, -0.28, 0.08, -0.06, -0.21, -0.05, 0.25, -0.17, -0.43,
  0.18, 0.14, 0.62, 0.21, 0.52, 0.28, 0.37, 0.22, 0.86, 0.93,
  0.92, 0.84, 0.37, 0.37, 0.99, 0.69, 0.53, 0.90, 0.80, 1.27,
  0.34, 0.69, 0.16, 1.28, 0.90
];

function rollingMean(values, windowSize = 5) {
  const halfWindow = Math.floor(windowSize / 2);
  return values.map((_, index) => {
    const start = Math.max(0, index - halfWindow);
    const end = Math.min(values.length - 1, index + halfWindow);
    const slice = values.slice(start, end + 1);
    const average = slice.reduce((sum, value) => sum + value, 0) / slice.length;
    return Number(average.toFixed(3));
  });
}

function linearTrend(values) {
  const n = values.length;
  const xMean = (n - 1) / 2;
  const yMean = values.reduce((sum, value) => sum + value, 0) / n;
  let numerator = 0;
  let denominator = 0;

  for (let i = 0; i < n; i += 1) {
    const xDelta = i - xMean;
    numerator += xDelta * (values[i] - yMean);
    denominator += xDelta * xDelta;
  }

  const slope = numerator / denominator;
  const intercept = yMean - slope * xMean;
  return values.map((_, i) => Number((intercept + slope * i).toFixed(3)));
}

const hotDaysMean5 = rollingMean(hotDays, 5);
const anomalyMean5 = rollingMean(anomaly, 5);
const hotDaysTrend = linearTrend(hotDays);
const anomalyTrend = linearTrend(anomaly);

const hotDaysChart = echarts.init(document.getElementById('chart-hot-days'));
const anomalyChart = echarts.init(document.getElementById('chart-anomaly'));

const slider = document.getElementById('year-slider');
const yearLabel = document.getElementById('year-label');
const playToggle = document.getElementById('play-toggle');

slider.min = 0;
slider.max = String(years.length - 1);
slider.value = String(years.length - 1);

let visibleIndex = years.length - 1;
let intervalId;

function truncateToVisible(values) {
  return values.map((value, i) => (i <= visibleIndex ? value : null));
}

function hotDaysBelowMean(values, meanValues) {
  return values.map((value, i) => Math.min(value, meanValues[i]));
}

function hotDaysAboveMean(values, meanValues) {
  return values.map((value, i) => Math.max(0, value - meanValues[i]));
}

function updateHotDaysChart() {
  const belowMean = hotDaysBelowMean(hotDays, hotDaysMean5);
  const aboveMean = hotDaysAboveMean(hotDays, hotDaysMean5);

  hotDaysChart.setOption({
    animationDuration: 700,
    animationDurationUpdate: 450,
    animationEasing: 'cubicOut',
    grid: { left: 64, right: 24, top: 36, bottom: 48 },
    legend: {
      right: 0,
      top: 0,
      itemWidth: 36,
      itemHeight: 10,
      textStyle: { color: '#2d3139', fontSize: 16 }
    },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const year = params[0]?.axisValue;
        const yearIndex = years.indexOf(Number(year));
        const under = belowMean[yearIndex] ?? 0;
        const above = aboveMean[yearIndex] ?? 0;
        const total = hotDays[yearIndex] ?? 0;
        const mean = hotDaysMean5[yearIndex] ?? 0;
        const meanLine = params.find((item) => item.seriesName === '5-year mean');
        const meanMarker = meanLine?.marker ?? '';

        return [
          `<strong>${year}</strong>`,
          `<span style="color:#8fa4ff">●</span> Hot days (under mean): ${under.toFixed(1)}`,
          `<span style="color:#ff1744">●</span> Hot days (above mean): ${above.toFixed(1)}`,
          `<span style="color:#2d3139">●</span> Hot days (total): ${total.toFixed(1)}`,
          `${meanMarker} 5-year mean: ${Number(mean).toFixed(1)}`,
          `<span style="color:#ff7aa8">●</span> Trend: ${Number(hotDaysTrend[yearIndex] ?? 0).toFixed(1)}`
        ].join('<br/>');
      }
    },
    xAxis: {
      type: 'category',
      data: years,
      axisLabel: { color: '#666b78' },
      axisLine: { lineStyle: { color: '#cfd4dd' } },
      splitLine: { show: true, lineStyle: { color: '#d9dde4' } }
    },
    yAxis: {
      type: 'value',
      name: 'Days / year',
      nameTextStyle: { color: '#666b78', fontSize: 15, padding: [0, 0, 8, 0] },
      axisLabel: { color: '#666b78' },
      splitLine: { lineStyle: { color: '#d9dde4' } }
    },
    series: [
      {
        name: 'Hot days (baseline P90)',
        type: 'bar',
        stack: 'hot-days',
        data: truncateToVisible(belowMean),
        itemStyle: { color: '#ccccff' }
      },
      {
        name: 'Hot days (baseline P90)',
        type: 'bar',
        stack: 'hot-days',
        data: truncateToVisible(aboveMean),
        itemStyle: { color: '#ff1744' }
      },
      {
        name: '5-year mean',
        type: 'line',
        data: truncateToVisible(hotDaysMean5),
        smooth: 0.35,
        symbol: 'none',
        lineStyle: { width: 4, color: '#1736ff' }
      },
      {
        name: 'Trend',
        type: 'line',
        data: hotDaysTrend,
        smooth: false,
        symbol: 'none',
        lineStyle: { width: 3, color: '#cccccc' },
        areaStyle: { color: 'rgba(255, 0, 0, 0.4)' }
      }
    ]
  });
}

function updateAnomalyChart() {
  anomalyChart.setOption({
    animationDuration: 700,
    animationDurationUpdate: 450,
    animationEasing: 'cubicOut',
    grid: { left: 64, right: 24, top: 36, bottom: 48 },
    legend: {
      right: 0,
      top: 0,
      itemWidth: 36,
      itemHeight: 10,
      textStyle: { color: '#2d3139', fontSize: 16 }
    },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: years,
      axisLabel: { color: '#666b78' },
      axisLine: { lineStyle: { color: '#cfd4dd' } },
      splitLine: { show: true, lineStyle: { color: '#d9dde4' } }
    },
    yAxis: {
      type: 'value',
      name: 'SST anomaly (°C)',
      nameTextStyle: { color: '#666b78', fontSize: 15, padding: [0, 0, 8, 0] },
      axisLabel: { color: '#666b78' },
      splitLine: { lineStyle: { color: '#d9dde4' } }
    },
    series: [
      {
        name: 'Annual mean anomaly',
        type: 'line',
        data: truncateToVisible(anomaly),
        smooth: 0.35,
        symbol: 'none',
        lineStyle: { width: 3, color: '#ff2e55' },
      },
      {
        name: '5-year mean',
        type: 'line',
        data: truncateToVisible(anomalyMean5),
        smooth: 0.35,
        symbol: 'none',
        lineStyle: { width: 4, color: '#1736ff' }
      },
      {
        name: 'Trend',
        type: 'line',
        data: truncateToVisible(anomalyTrend),
        smooth: false,
        symbol: 'none',
        lineStyle: { width: 3, color: '#cccccc' },
        areaStyle: { color: 'rgba(255, 0, 0, 0.4)' }
      }
    ]
  });
}

function updateAllCharts() {
  slider.value = String(visibleIndex);
  yearLabel.textContent = String(years[visibleIndex]);
  updateHotDaysChart();
  updateAnomalyChart();
}

function stopPlayback() {
  clearInterval(intervalId);
  intervalId = undefined;
  playToggle.textContent = 'Play';
}

function startPlayback() {
  if (visibleIndex >= years.length - 1) {
    visibleIndex = 0;
  }

  playToggle.textContent = 'Pause';
  intervalId = window.setInterval(() => {
    if (visibleIndex >= years.length - 1) {
      stopPlayback();
      return;
    }

    visibleIndex += 1;
    updateAllCharts();
  }, 320);
}

playToggle.addEventListener('click', () => {
  if (intervalId) {
    stopPlayback();
    return;
  }
  startPlayback();
});

slider.addEventListener('input', () => {
  visibleIndex = Number(slider.value);
  stopPlayback();
  updateAllCharts();
});

window.addEventListener('resize', () => {
  hotDaysChart.resize();
  anomalyChart.resize();
});

updateAllCharts();
