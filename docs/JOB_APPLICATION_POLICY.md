# Job Application Policy

This policy dictates the rules for evaluating and recommending job applications. The overarching goal is to prevent high-volume, poorly targeted applications, and instead optimize for interview likelihood by focusing on strong candidate-role fit.

## Core Rules

1. **Missing Description**: No full job description means **blocked** (no application recommendation). The system is blocked from recommending jobs without adequate information.
2. **Campaign Assignment**: Every job must belong to one defined campaign.
3. **Hard Disqualifiers**: Any hard disqualifier means **reject**. There are no exceptions, regardless of numeric score.
4. **Minimum Score**: A normal application recommendation requires a `fit_score` of **at least 82**.
5. **Evidence Requirement**: Every recommendation (recommend or strong_recommend) requires `evidence_mappings >= 3` (at least three valid evidence matches) referencing verified career accomplishments.
6. **Unknown Information**: Missing information remains unknown and receives no scoring credit. Missing data must not be interpreted in the candidate's favor.
    - Unknown salary earns zero compensation/employment points.
    - Unknown location earns zero location/work-arrangement points.
    - Adjacent technology is not direct experience.
    - Assumed learning ability is not verified evidence.
    - General architecture experience does not satisfy an unrelated architecture discipline.
7. **Resume Identification**: Every application must identify a resume version.
8. **Human Approval**: Every application requires **explicit human approval**.
9. **Rejection Traceability**: Rejected jobs must retain a rejection reason.
10. **No Automation**: No automatic application submission tool may be added to this system.
