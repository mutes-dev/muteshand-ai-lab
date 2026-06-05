/**
 * DangerConfirmModal — shared in-app destructive action confirmation modal.
 *
 * Replaces native browser window.confirm for destructive actions across the UI.
 * Visually consistent: dark modal, red danger border, strong confirm button, backdrop dismiss.
 *
 * Props:
 *   config  — null (hidden) or { title, confirmLabel, rows: [{label, value}] }
 *   onConfirm — called when user clicks the confirm button
 *   onCancel  — called when user clicks Cancel or the backdrop
 */
export default function DangerConfirmModal({ config, onConfirm, onCancel }) {
  if (!config) return null;
  return (
    <div className="memory-modal-backdrop" onClick={onCancel}>
      <div className="memory-modal" onClick={(e) => e.stopPropagation()}>
        <div className="memory-modal-header">
          <span className="memory-modal-icon">⚠</span>
          <h3 className="memory-modal-title">{config.title}</h3>
        </div>
        <div className="memory-modal-body">
          {config.rows.map((row) => (
            <div key={row.label} className="memory-modal-row">
              <span className="memory-modal-label">{row.label}:</span>
              <span className="memory-modal-value">{row.value}</span>
            </div>
          ))}
          {config.warning && (
            <p className="memory-modal-warning">{config.warning}</p>
          )}
          {!config.warning && (
            <p className="memory-modal-warning">This action cannot be undone.</p>
          )}
        </div>
        <div className="memory-modal-actions">
          <button className="memory-modal-btn-cancel" onClick={onCancel}>
            Cancel
          </button>
          <button className="memory-modal-btn-confirm" onClick={onConfirm}>
            {config.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
