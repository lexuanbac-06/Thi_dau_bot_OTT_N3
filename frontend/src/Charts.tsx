export type ChartDatum = { label: string; value: number; tone?: 'blue' | 'green' | 'amber' | 'red' | 'muted' };

function ChartSkeleton() {
  return <div className="chart-skeleton" aria-hidden="true"><i /><i /><i /><i /></div>;
}

export function ColumnChart({ title, data, loading }: { title: string; data: ChartDatum[]; loading?: boolean }) {
  const max = Math.max(1, ...data.map((item) => item.value));
  return (
    <figure className="chart-card">
      <figcaption>{title}</figcaption>
      {loading ? <ChartSkeleton /> : !data.length ? <p className="chart-empty">Chưa có dữ liệu.</p> : (
        <div className="column-chart" role="img" aria-label={`${title}: ${data.map((item) => `${item.label} ${item.value}`).join(', ')}`}>
          {data.map((item) => (
            <div className="column-item" key={item.label}>
              <strong>{item.value}</strong>
              <span className={`column-bar tone-${item.tone || 'blue'}`} style={{ height: `${Math.max(item.value ? 6 : 2, (item.value / max) * 100)}%` }} />
              <small>{item.label}</small>
            </div>
          ))}
        </div>
      )}
    </figure>
  );
}

export function BarList({ title, data, loading }: { title: string; data: ChartDatum[]; loading?: boolean }) {
  const total = data.reduce((sum, item) => sum + item.value, 0);
  return (
    <figure className="chart-card">
      <figcaption>{title}</figcaption>
      {loading ? <ChartSkeleton /> : !data.length ? <p className="chart-empty">Chưa có dữ liệu.</p> : (
        <>
          <div className="stack-bar" role="img" aria-label={title}>
            {data.filter((item) => item.value > 0).map((item) => (
              <span key={item.label} className={`tone-${item.tone || 'blue'}`} style={{ flex: item.value }} title={`${item.label}: ${item.value}`} />
            ))}
          </div>
          <ul className="bar-list">
            {data.map((item) => (
              <li key={item.label}>
                <span className={`legend-dot tone-${item.tone || 'blue'}`} />
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <small>{total ? Math.round((item.value / total) * 100) : 0}%</small>
              </li>
            ))}
          </ul>
        </>
      )}
    </figure>
  );
}
