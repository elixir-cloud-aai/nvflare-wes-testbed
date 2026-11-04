# Requirements

Numbered: user (R-U), security (R-S) and privacy (R-P). Each says what, why, and which part of the [use case](use-case.md) it comes from. None says how.

## User

| ID | What | Why | From |
|---|---|---|---|
| R-U1 | Start a federated job through the same interface as other analyses | One way to run things | Step 1 |
| R-U2 | Choose which institutions take part | Collaborations differ | Step 1 |
| R-U3 | Follow the job's state, and see which part ran where | Long-running, across organizations | Step 4 |
| R-U4 | Get the final model, and a clear failure if there's none | The point of the exercise | Step 4 |
| R-U5 | Reuse a job definition without changing it for each institution | The procedure is the same everywhere | Step 2 |

## Security

| ID | What | Why | From |
|---|---|---|---|
| R-S1 | Only authorized people can start a job | Institutions' compute isn't public | Step 1 |
| R-S2 | Participants prove to each other who they are, and their traffic is protected | Intermediate results travel across organizations | Step 3 |
| R-S3 | An institution needs no inbound access from outside | Institutions' firewalls | Step 2 |
| R-S4 | An institution's credentials stay with that institution | One compromised party mustn't compromise others | Step 2 |
| R-S5 | Institutions can refuse a procedure, or limit what it does | Institutions decide what runs | Step 2 |
| R-S6 | Credentials end with the job they were issued for | Limits the damage of a leak | Step 3 |

## Privacy

| ID | What | Why | From |
|---|---|---|---|
| R-P1 | Data never leaves its institution | The premise of the use case | Step 2 |
| R-P2 | No party, including the coordinator, needs access to an institution's data | Same | Step 3 |
| R-P3 | Institutions can limit what intermediate results reveal | Results can leak what they were computed from | Step 3 |
| R-P4 | The record of a job holds who, what and where, not data | Attribution without exposure | Step 4 |

## Fit with TES and WES

Federated training differs from what those services usually run, in ways any design has to answer: its participants are long-running and talk to each other while running, whereas a batch task runs on its own and hands over its outputs when it ends.
