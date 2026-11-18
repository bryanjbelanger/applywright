# Job Screening Workflow

The job screening workflow is a human-in-the-loop process designed to optimize for interview likelihood over volume.

## Implementation Status

Only part of this design exists. The MCP server has these tools:

| Step | Design name | MCP tool today |
| --- | --- | --- |
| 1 | `evaluate_job` | `prepare_job_evaluation` builds the context. `validate_job_evaluation` checks a proposed evaluation. Neither stores the result. |
| 2 | `save_job_evaluation` | Not implemented. |
| 3 | `approve_job` | Not implemented. |
| 4 | `record_application` | Not implemented. `mark_job` with decision `applied` records a submission on the job row. |

Sections 1 to 4 describe the target design. Names below are design names, not tool names.

## Pipeline Steps

### 1. Evaluation (`evaluate_job`)
- **Purpose**: Reads the job description and generates a 100-point `fit_score` against the candidate profile.
- **Validation**:
  - Requires a valid `job_id`.
  - Must explicitly establish description availability (`description_available: true`).
  - Output contains the calculated score, `evidence_matches`, detected campaigns, and any hard disqualifiers.
  - Missing information remains unknown and receives no scoring credit. Unknowns are preserved separately from material gaps.

### 2. Save Evaluation (`save_job_evaluation`)
- **Purpose**: Saves the `fit_score`, `evidence_matches`, and decision payload.
- **Validation**:
  - Enforces policy thresholds and overrides before applying numeric thresholds.
  - Rejects evaluations where `fit_score` is out of bounds (0-100).
  - Must fail recommendations (`recommend` or `strong_recommend`) if there is no description, any hard disqualifier exists, or if `< 3` valid `evidence_matches` are provided.

### 3. Human Approval (`approve_job`)
- **Purpose**: Manual transition to mark a job ready for application.
- **Validation**:
  - Requires `job_id` and the exact `resume_version` at approval time. A job must not be approved while resume selection is pending.
  - Fails unless ALL of the following are true:
    - the full description exists
    - the campaign is valid
    - `fit_score` is at least 82
    - recommendation is `recommend` or `strong_recommend`
    - no hard disqualifiers exist
    - at least three valid evidence mappings exist (`evidence_mappings >= 3`)
    - `resume_version` is supplied
    - explicit human approval is recorded, including `approved_by` and `approved_at`
  - A `manual_review` result cannot be approved unless reevaluation raises `fit_score` to at least 82.

### 4. Record Application (`record_application`)
- **Purpose**: Records an externally completed submission. It must **never submit an application**.
- **Validation**:
  - Requires an existing approval.
  - References the approved evaluation.
  - Requires the same `resume_version` used in approval.
  - Is idempotent and prevents duplicate application records.
  - Records `applied_at` and retains `application_url` or `submission_reference` when available.
  - Preserves evaluation and approval history.

## Future Database Schema Design

To preserve history and auditability, future implementation should use separate tables equivalent to:

```text
job_evaluations:
- evaluation_id
- job_id
- campaign_id
- fit_score
- recommendation
- fit_summary
- strengths
- material_gaps
- unknowns
- hard_disqualifiers
- evidence_matches
- policy_version
- candidate_profile_version
- evaluated_at

job_approvals:
- approval_id
- job_id
- evaluation_id
- resume_version
- approved_by
- approved_at

job_applications:
- application_id
- job_id
- approval_id
- resume_version
- applied_at
- application_url
- submission_reference
- outcome
```
