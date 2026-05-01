# Lecture 4 Summary: Cloud CPU Scheduling

## 1. Big Picture
CPU scheduling in cloud virtualization decides which VM runs next on host CPU(s).

Why this matters:
- Multiple VMs contend for CPU resources.
- Cloud platforms must provide performance guarantees and isolation.
- Hypervisor-level policy directly affects fairness, utilization, and SLA behavior.

## 2. Core Motivation and Concepts
| Concept | Meaning | Exam Focus |
|---|---|---|
| CPU scheduling location | Implemented in hypervisor | Distinguish guest OS scheduling vs hypervisor scheduling |
| Fairness | CPU share proportional to configured policy (weight/priority) | Know weighted sharing intuition |
| Utilization | How much CPU is kept busy when VMs are idle/busy | Work-conserving vs non-work-conserving |
| Isolation | Prevent one VM from dominating CPU | Understand role of weights/caps |

## 3. Fairness vs Utilization Tradeoff
| Mode | Rule | Pros | Cons |
|---|---|---|---|
| Work-conserving (WC) | CPU idle only if no runnable VM; idle share can be borrowed | High utilization | Can reduce strict fairness/isolation |
| Non-work-conserving (NWC) | VM share can be capped even if CPU idle | Strong fairness/isolation guarantees | Lower utilization |

Exam memory line:
- WC maximizes efficiency.
- NWC strengthens strict resource control.

## 4. SEDF Scheduler (Simple Earliest Deadline First)
SEDF models each VM request as tuple $(s_i, p_i, x_i)$:
- $s_i$: CPU time requested per period
- $p_i$: period length
- $x_i$: extra-time flag ($1$ = can consume slack in WC mode, $0$ = no extra)

### 4.1 Runtime Variables and Decision Rule
| Symbol | Meaning |
|---|---|
| $d_i$ | End time of current period (deadline) |
| $r_i$ | Remaining CPU time in current period |

Scheduling rule:
- At each slot, among runnable VMs with $r_i > 0$, run VM with earliest deadline $d_i$.
- Ties can be broken arbitrarily.

### 4.2 SEDF Mathematical Conditions
| Item | Formula / Condition | Interpretation |
|---|---|---|
| VM utilization demand | $u_i = s_i / p_i$ | Fraction of CPU VM $i$ needs |
| Total utilization | $U = \sum_i (s_i / p_i)$ | Aggregate required CPU share |
| Schedulability (single CPU) | $\sum_i (s_i / p_i) \leq 1$ | VM set is admissible iff condition holds |
| Pattern repetition window | $\text{lcm}(p_1, p_2, \ldots, p_n)$ | Schedule repeats every least common multiple |

### 4.3 SEDF Mode Behavior
| Case | Behavior |
|---|---|
| $x_i = 0$ (NWC) | $r_i$ resets to $s_i$ only at period boundaries |
| $x_i = 1$ (WC) | When $r_i$ hits 0, it can be replenished for extra-time use if VM remains runnable |

### 4.4 SEDF Worked Micro Example
Given:
- VM1: $(1,2,0)$ $\Rightarrow$ $u_1 = 1/2 = 0.5$
- VM2: $(2,7,0)$ $\Rightarrow$ $u_2 = 2/7 \approx 0.286$

Then:
- $U = 0.5 + 0.286 = 0.786 \leq 1$ $\rightarrow$ schedulable
- Hyperperiod $= \text{lcm}(2,7) = 14$
- It is enough to analyze first 14 slots to infer repeating pattern.

### 4.5 SEDF Strengths and Limits
| Strengths | Limitations |
|---|---|
| Supports WC/NWC behavior | Fairness sensitive to period granularity choice |
| Clear admission test via utilization | Per-CPU scheduler; lacks global multiprocessor load balancing |

## 5. Xen Credit Scheduler
Default Xen proportional-share scheduler with automatic load balancing across physical CPUs.

### 5.1 Main Controls
| Parameter | Meaning | Typical note |
|---|---|---|
| Weight | Relative share in proportional allocation | Default 256, range [1, 65535] |
| Cap | Max CPU percentage allowed (even if CPU idle) | `0` means uncapped/WC; e.g., `30` means <=30% |

### 5.2 Credit Scheduler Mechanics
| Mechanism | Description |
|---|---|
| Time slot | 30 ms scheduling quantum |
| VM state | `under` or `over` (relative to fair-share usage in accounting period) |
| Run queue | Per-CPU FIFO queue; `under` VMs prioritized before `over` |
| Accounting | Credits consumed when running; system periodically refills credits proportionally to weight |
| Multiprocessor behavior | Supports global load balancing across pCPUs |

### 5.3 Credit Allocation Math (Exam View)
If active VMs have weights $w_1, w_2, \ldots, w_n$, then the ideal proportional share for VM $i$ is:

$$\text{share}_i = \frac{w_i}{\sum_j w_j}$$

If total distributable credits in an accounting window are $C_{\text{total}}$, then VM $i$ receives approximately:

$$C_i = C_{\text{total}} \cdot \frac{w_i}{\sum_j w_j}$$

Worked ratio example:
- VM1 weight = 256, VM2 weight = 512
- Shares: VM1 = $1/3$, VM2 = $2/3$
- If 15 credits allocated in window: VM1 gets 5, VM2 gets 10

## 6. SEDF vs Credit Scheduler (Exam Comparison)
| Dimension | SEDF | Credit Scheduler |
|---|---|---|
| Policy style | Deadline + reservation tuple $(s,p,x)$ | Proportional-share via weight/cap |
| Admission logic | Explicit utilization test | Implicit via credits and queue states |
| WC/NWC support | Yes ($x_i$) | Yes (cap/uncapped mode) |
| Multiprocessor load balancing | Weak (per-CPU limitation) | Stronger (automatic balancing) |
| Practicality in Xen | Older model studied for guarantees | Default and operationally simple |

## 7. High-Yield Formulas Sheet
| Topic | Formula |
|---|---|
| SEDF VM demand | $u_i = s_i / p_i$ |
| SEDF schedulability | $\sum_i (s_i / p_i) \leq 1$ |
| Hyperperiod | $\text{lcm}(p_1, \ldots, p_n)$ |
| Credit share | $$\text{share}_i = \frac{w_i}{\sum_j w_j}$$ |
| Credit amount | $C_i = C_{\text{total}} \cdot w_i / \sum_j w_j$ |

## 8. Typical Exam Workflow
1. Convert each VM requirement into utilization ($s_i/p_i$).
2. Check schedulability inequality.
3. Compute $\text{lcm}$ of periods to determine repeating schedule window.
4. For credit scheduler questions, reduce weights to ratios.
5. Apply caps to distinguish WC vs NWC behavior in final allocation.

## 9. Must-Memorize Points
1. CPU scheduling is a hypervisor-level cloud control problem.
2. Fairness and utilization are in tension; WC vs NWC determines the balance.
3. SEDF tuple $(s_i, p_i, x_i)$ is the key abstraction.
4. SEDF feasibility requires total requested utilization <= 1 on a single CPU.
5. Credit scheduler uses weight/cap and under/over states with periodic credit accounting.
6. Xen credit scheduler is practical and supports global load balancing.
