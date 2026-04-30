# Lecture 3 Summary: Virtualization in Cloud

## 1. Big Picture
Virtualization abstracts physical resources (CPU, memory, storage, network) so multiple isolated environments can run on the same hardware.

Why it matters in cloud:
- Better hardware utilization
- Faster provisioning (elasticity)
- Isolation between workloads
- Easier management, migration, and scaling

## 2. Core Concept (Exam Table)
| Item | Non-Virtualized Model | Virtualized Model |
|---|---|---|
| Server usage | One server per application (low utilization) | Multiple VMs per physical host (higher utilization) |
| HW/SW coupling | Tight coupling | Decoupled via virtualization layer |
| Isolation | Process-level only | VM-level strong isolation |
| Scaling | Slow (buy/install server) | Fast (start VM instance/image) |

## 3. Key Architectures

### 3.1 Hosted vs Hypervisor Architecture
| Architecture | Where virtualization layer runs | Hardware access path | Typical use | Main tradeoff |
|---|---|---|---|---|
| Hosted | As an application on top of host OS | Indirect via host OS | Desktop/dev/testing | Easier setup, lower performance |
| Bare-metal Hypervisor | Directly on hardware | Direct | Production/cloud DC | Higher performance, better scalability/robustness |

Exam memory line:
- Hosted = convenience first
- Bare-metal hypervisor = performance and production first

## 4. OS/CPU Basics Needed for Virtualization

### 4.1 Fundamental OS Concepts
| Concept | Meaning | Why virtualization cares |
|---|---|---|
| Thread | Single execution context (PC, registers, stack) | CPU state must be switched/saved/restored correctly |
| Address space | Program-visible virtual memory | Isolation and memory translation are essential |
| Process | Address space + one/more threads + resources | VM isolation builds on protection ideas |
| Dual mode | User mode vs kernel (privileged) mode | Hypervisor must control privileged operations |

### 4.2 Protection and Privilege
| Mechanism | Purpose |
|---|---|
| Privileged instructions | Restrict sensitive operations to trusted layer |
| Address translation | Protect OS/processes from unauthorized memory access |
| Trap/syscall/interrupt flow | Controlled transition between unprivileged and privileged execution |
| Protection rings (x86) | Hardware-enforced privilege hierarchy |

## 5. Types of CPU Virtualization

### 5.1 Comparison Table
| Type | How it works | Guest OS modification | Performance | Typical notes |
|---|---|---|---|---|
| Full virtualization | Hypervisor emulates full hardware; traps/translates sensitive ops | No | Lower (emulation/translation overhead) | Maximum compatibility |
| Para-virtualization | Guest OS is virtualization-aware; uses hypercalls | Yes (or PV drivers) | Better than full virtualization | Needs guest support |
| Hardware-assisted virtualization | CPU features (e.g., Intel VT-x, AMD-V) provide virtualization support | Usually no major guest changes | Best practical server performance | Dominant in modern clouds |

### 5.2 Full Virtualization Notes
| Aspect | Key idea |
|---|---|
| Binary translation | Non-virtualizable privileged instructions translated into safe sequences |
| Trap-and-emulate | Sensitive guest operations trapped by hypervisor and emulated |
| Benefit | Unmodified guest OS portability |
| Drawback | Performance penalty compared with newer approaches |

### 5.3 Para-Virtualization Notes
| Aspect | Key idea |
|---|---|
| Hypercalls | Guest explicitly calls hypervisor for privileged services |
| Guest awareness | Guest kernel knows it is virtualized |
| Benefit | Reduced emulation overhead, improved performance |
| Limitation | Requires modified guest kernel or PV drivers |

## 6. Virtualization and IaaS Cloud

Cloud relevance:
- Elasticity depends on fast VM lifecycle operations.
- Cloud infrastructure is effectively a VM management system.

### 6.1 IaaS Building Blocks (from lecture flow)
| Component | Role |
|---|---|
| Controller node | Orchestration/scheduling/control |
| Compute node | Runs VM instances |
| VM image storage | Stores reusable VM images |
| SAN/iSCSI path | Provides network-accessible storage and image transfer |

### 6.2 Why VM abstraction enables cloud business model
| Capability | Cloud effect |
|---|---|
| Image-based deployment | Rapid launch/replication of instances |
| Isolation | Multi-tenant sharing with lower interference risk |
| Encapsulation | Move/start/stop/resume instances quickly |
| Decoupling from hardware | Easier scaling and operations across heterogeneous servers |

## 7. Storage Virtualization: RAID (High-Yield)
The lecture extends virtualization ideas to storage: combine multiple physical disks into one logical virtual disk system.

### 7.1 RAID Levels in Lecture
| RAID Level | Method | Capacity efficiency | Fault tolerance | Performance notes |
|---|---|---|---|---|
| RAID 0 | Striping only | High (all disks usable) | None (1 disk failure can fail array) | High throughput |
| RAID 1 | Mirroring | ~50% usable | Survives single-disk failure per mirror pair | Good read performance, higher storage cost |
| RAID 5 | Striping + distributed parity (XOR) | Loses ~1 disk worth | Survives 1 disk failure | Writes incur parity update overhead |
| RAID 6 | Striping + dual parity (e.g., RS coding) | Loses ~2 disks worth | Survives 2 disk failures | Better resilience for large arrays |

### 7.2 How each RAID works (illustrative)
| RAID | Data layout and write path | What happens on failure |
|---|---|---|
| RAID 0 | Data is striped across disks in chunks. Example with 4 disks: block sequence A1, A2, A3, A4 goes to Disk1..Disk4, then next stripe B1..B4, etc. | Any single disk failure loses part of every striped file, so array becomes unusable. |
| RAID 1 | Every write is duplicated to a mirror disk (or mirror set). Reads can come from either copy. | If one disk in a mirror fails, data is still served from the surviving mirror member. |
| RAID 5 | For each stripe, one block is parity (XOR of data blocks), and parity position rotates across disks. Small writes usually require read-old-data + read-old-parity + write-new-data + write-new-parity. | Survives one disk failure by reconstructing missing block using XOR of remaining blocks in stripe. |
| RAID 6 | Similar to RAID 5 but with two independent parity blocks (commonly P and Q) per stripe. | Survives any two disk failures in the same array; recovery uses coding equations from surviving blocks. |

### 7.3 Mathematical formulas (capacity, reliability, performance)
Assume:
- number of disks = n
- size per disk = S
- independent single-disk failure probability in a period = p

| RAID | Usable capacity | Storage efficiency | Fault tolerance |
|---|---|---|---|
| RAID 0 | nS | 1 | 0 disk failures |
| RAID 1 (pairs) | (n/2)S | 1/2 | 1 failure per mirror pair |
| RAID 5 | (n-1)S | (n-1)/n | any 1 disk failure |
| RAID 6 | (n-2)S | (n-2)/n | any 2 disk failures |

Approximate array failure probability in one period (small p approximation):
- RAID 0: P(fail) = 1 - (1 - p)^n approximately np
- RAID 1 with n/2 mirrored pairs: P(fail) = 1 - (1 - p^2)^(n/2) approximately (n/2)p^2
- RAID 5 (2+ failures): P(fail) approximately C(n,2)p^2
- RAID 6 (3+ failures): P(fail) approximately C(n,3)p^3

Write penalty (small random writes, conceptual I/O count):
- RAID 0: ~1 data write
- RAID 1: ~2 writes (both mirrors)
- RAID 5: ~4 I/Os (read old data, read old parity, write new data, write new parity)
- RAID 6: ~6 I/Os (similar idea with two parities)

### 7.4 XOR parity idea and recovery equations
| Given | Recover missing value |
|---|---|
| P = A XOR B XOR C XOR ... | Missing block X = P XOR (XOR of all surviving data blocks in the stripe) |

Mini example (RAID 5 stripe):
- Data blocks: D1 = 5, D2 = 9, D3 = 12
- Parity: P = D1 XOR D2 XOR D3
- If D2 fails, reconstruct by D2 = P XOR D1 XOR D3

Why this matters:
- Enables reconstruction after disk failure with less storage overhead than full replication.

### 7.5 Quick exam compare: when to use which RAID
| RAID | Best when | Not ideal when |
|---|---|---|
| RAID 0 | Need maximum throughput/capacity and data is disposable or replicated elsewhere | Need reliability |
| RAID 1 | Need simple strong redundancy and fast reads | Capacity efficiency is critical |
| RAID 5 | Need balanced capacity + single-failure protection | Heavy random write workloads |
| RAID 6 | Large arrays where dual-failure tolerance is required | Very write-heavy workloads with low latency targets |

## 8. Practical Performance Themes
| Theme | Exam interpretation |
|---|---|
| Latency hierarchy (ns to ms scale) | Data location dominates performance decisions |
| Caching everywhere | Trade memory/cost for lower average access latency |
| VM overhead considerations | Architecture choice (hosted/PV/HW-assisted) impacts end-to-end app performance |

## 9. Advantages and Limitations of Virtualization
| Advantages | Limitations / Risks |
|---|---|
| Higher utilization and consolidation | Overhead (especially older full virtualization) |
| Fast provisioning and elasticity | Performance unpredictability under contention |
| Isolation and portability | Complexity in management and security hardening |
| Easy replication and scale-out | Storage/network bottlenecks still apply |

## 10. Exam Quick Compare Sheet
| Dimension | Hosted | Full Virtualization | Para-Virtualization | Hardware-Assisted |
|---|---|---|---|---|
| Layer position | Above host OS | Hypervisor controls VM with emulation | Hypervisor + guest cooperation | Hypervisor + CPU virtualization extensions |
| Guest OS changes needed | No | No | Yes/partial | Usually no |
| Performance | Lowest among these | Moderate-lower | Higher | Highest practical |
| Typical scenario | Desktop/lab | Compatibility-focused environments | Tuned deployments | Modern cloud data centers |

## 11. Must-Memorize Points
1. Virtualization separates software environments from physical hardware.
2. Hypervisor (bare-metal) is preferred for production cloud due to direct hardware access.
3. CPU virtualization methods: full, para, hardware-assisted; each trades compatibility vs performance.
4. Dual-mode protection and privileged instruction control are central to safe virtualization.
5. Cloud IaaS is fundamentally VM/image orchestration over compute and storage infrastructure.
6. RAID is storage virtualization: striping/parity/mirroring trade capacity, performance, and resilience.
7. Elastic cloud behavior is enabled by rapid VM creation, migration, and replication.
