/**
 * Table showing open positions.
 * @param {Object} positions - map of symbol → position data
 */
export default function PositionsTable({ positions }) {
  const entries = Object.entries(positions || {});

  if (entries.length === 0) {
    return <div className="loading">No open positions.</div>;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Asset</th>
            <th>Size</th>
            <th>Entry</th>
            <th>Current</th>
            <th>P&L</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([symbol, pos]) => {
            const pnl = parseFloat(pos.unrealized_pnl) || 0;
            return (
              <tr key={symbol}>
                <td>{symbol}</td>
                <td>{parseFloat(pos.size).toFixed(6)}</td>
                <td>${parseFloat(pos.entry_price).toLocaleString()}</td>
                <td>${parseFloat(pos.current_price).toLocaleString()}</td>
                <td style={{ color: pnl >= 0 ? "var(--green)" : "var(--red)" }}>
                  ${pnl.toFixed(4)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
