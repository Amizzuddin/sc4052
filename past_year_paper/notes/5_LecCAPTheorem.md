# Lecture 5 Summary: CAP Theorem

![CAP theorem tradeoff diagram](cap_theorem_tradeoff.jpg)

## 1. Big Picture
CAP theorem explains a core tradeoff in distributed systems.

Historical context:
- Conjectured by Eric Brewer (2000).
- Formalized/proven by Gilbert and Lynch (2002).

Key message for cloud systems:
- In the presence of network partitions, a system cannot provide both full consistency and full availability at the same time.

## 2. CAP Definitions (Exam Table)
| Property | Meaning in this lecture | Practical interpretation |
|---|---|---|
| Consistency (C) | All nodes see the same data at the same time | Reads return latest committed value everywhere |
| Availability (A) | Surviving nodes continue to respond | Every request gets a response (success/failure) |
| Partition Tolerance (P) | System continues operating despite network partition | System keeps running even when links fail/split cluster |

## 3. Correct CAP Interpretation
Common shorthand says pick any 2 of 3 (CP, AP, CA), but for real cloud/distributed systems:
- Partitions are unavoidable in unreliable large-scale networks.
- So P is effectively mandatory.
- Real decision under partition is usually CP versus AP.

## 4. What Happens During Partition?
| Choice under partition | System behavior | Cost |
|---|---|---|
| Choose CP | Reject/block some requests to keep replicas consistent | Reduced availability |
| Choose AP | Continue serving requests in all partitions | Temporary inconsistency/divergence |

Exam memory line:
- Partition event forces consistency-vs-availability tradeoff.

## 5. Misconception Fix Table
| Misconception | Better statement |
|---|---|
| CAP is always a strict binary pick-two model | In practice, systems provide degrees of C and A around partition events |
| AP means no consistency | AP systems often provide weaker forms like eventual consistency |
| CP means system is unusable | CP systems are available for some operations/partitions, but may block conflicting ones |

## 6. AP and CP Characteristics
| Model | Typical examples from lecture | Typical traits |
|---|---|---|
| AP (best-effort consistency) | Web caching, DNS | Optimistic updates, TTL/expiration, conflict resolution |
| CP (best-effort availability) | Majority protocols, distributed locking (e.g., Chubby-style) | Pessimistic control, minority partition may become unavailable |

## 7. Consistency Models (High-Yield)
| Model | Definition | What user observes |
|---|---|---|
| Strong consistency | After update completes, all subsequent accesses return updated value | No stale reads after commit |
| Weak consistency | No guarantee subsequent accesses see latest update | Stale reads possible |
| Eventual consistency | If no new updates occur, all replicas eventually converge to latest value | Temporary staleness, eventual convergence |

## 8. Lecture Examples and Why They Matter
| Scenario | CAP-oriented insight |
|---|---|
| Facebook wall post delay | Eventual consistency improves scalability/availability but may delay visibility |
| ATM withdrawal during partition | Many systems prefer availability with bounded risk (limits/fees) |
| Airline reservations | Tradeoff can be dynamic: favor A when seats abundant, shift toward C near sellout |

## 9. CAP Decision Framework for Exam Questions
Use this sequence:
1. Ask if network partition is considered (usually yes in distributed/cloud questions).
2. Identify business priority during partition:
- Prevent divergence at all cost -> CP tendency.
- Keep service responsive at all cost -> AP tendency.
3. Specify consistency level (strong, weak, eventual) and operational controls (quorums, retries, TTL, conflict resolution).
4. State concrete impact on user-visible behavior (blocked requests vs stale reads).

## 10. Summary of Theorem (Exam-Ready)
In partitioned distributed systems:
- Keeping replicas fully consistent requires blocking some operations (appears unavailable).
- Serving all requests from all partitions can cause replica divergence (consistency weakened).
- CAP explains this unavoidable design dilemma.

## 11. Must-Memorize Points
1. CAP becomes most meaningful during partition scenarios.
2. For real cloud systems, P is generally non-negotiable.
3. Practical decision is usually CP versus AP under partition.
4. AP and CP are not all-or-nothing; systems operate on a spectrum of C and A.
5. Eventual consistency is a common AP-style design for internet-scale services.
6. Architecture should be chosen based on business risk of stale data vs downtime.
