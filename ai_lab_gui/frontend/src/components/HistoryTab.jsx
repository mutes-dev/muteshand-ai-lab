/**
 * History Tab - Phase 1 Placeholder
 * 
 * This is a placeholder component for the History functionality that will be
 * implemented in ISSUE-061 Phase 2. It does not load or display any workflows
 * and does not expose any actions.
 * 
 * Per WORKFLOW_RETENTION_AND_ARCHIVAL_CONTRACT_V1:
 * - History represents previously existing workflows
 * - History is observability-oriented and inspection-oriented
 * - History is non-actionable
 * 
 * Phase 1 placeholder requirements:
 * - Must not load historical workflows yet
 * - Must not expose actions
 * - Must not imply retry legality
 * - Must not imply recoverability
 * - Must not mutate lifecycle state
 * - Must not mutate retention_state
 * - Must not classify workflows
 * - Must not synthesize lifecycle/recoverability
 */

export default function HistoryTab() {
  return (
    <div className="history-tab">
      <div className="history-placeholder">
        <div className="history-placeholder-icon">📚</div>
        <h4>History Coming Soon</h4>
        <p>
          History view will show completed, cancelled, archived, dismissed, and historical 
          workflows for read-only inspection.
        </p>
        <p className="history-placeholder-note">
          Full History wiring is deferred to ISSUE-061 Phase 2.
        </p>
        
        <div className="history-placeholder-details">
          <h5>Future History Features:</h5>
          <ul>
            <li>Read-only historical workflow inspection</li>
            <li>Completed and cancelled workflow visibility</li>
            <li>Archived and dismissed workflow access</li>
            <li>Workflow timeline and chronology</li>
            <li>Execution lineage and retry ancestry</li>
          </ul>
        </div>
        
        <div className="history-placeholder-info">
          <p>
            <strong>Note:</strong> Archive will be implemented as a filter inside History, 
            not as a separate tab.
          </p>
        </div>
      </div>
    </div>
  );
}
