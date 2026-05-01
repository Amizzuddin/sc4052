################################################################################
#  Filename:      notes/convert_math.py                                        #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Friday, May 1st 2026, 11:39:54 am                            #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Friday May 1st 2026 11:41:21 am                              #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

"""
Convert backtick-code math expressions to proper LaTeX $...$ notation
in all lecture markdown files.
"""

import os

FILES = [
    "LectureNotesFullSummarize.md",
    "1_basics.md",
    "2_DataCenterNetworking.md",
    "3_Virtualization.md",
    "4_CPUCloudComputing.md",
    "5_LecCAPTheorem.md",
    "6a_LecCloudSecurity.md",
    "6b_LecCrowdsourcin.md",
    "6c_LecPageRank.md",
    "8a-LecAPIREST.md",
    "8b-LecBigDataComputing.md",
    "9a-CloudLLMAppsBasic.md",
    "10-LecConsistencyHashDynamo.md",
    "11-NoSQLDatabaseStory.md",
]

# ──────────────────────────────────────────────────────────────────────────────
# Ordered list of exact (old, new) substitutions.
# More specific / longer patterns must come BEFORE shorter overlapping ones.
# ──────────────────────────────────────────────────────────────────────────────
EXACT = [
    # ── Prose intro lines ────────────────────────────────────────────────────
    ("Let `W` be congestion window in MSS units.", "Let $W$ be the congestion window in MSS units."),
    ("Public parameters: prime `p`, generator `g`.", "Public parameters: prime $p$, generator $g$."),
    (
        "RSA relies on difficulty of factoring a large composite number `N = P*Q`.",
        r"RSA relies on difficulty of factoring a large composite number $N = P \cdot Q$.",
    ),
    (
        "If active VMs have weights `w_1, w_2, ..., w_n`, then ideal proportional share for VM `i` is:",
        r"If active VMs have weights $w_1, w_2, \ldots, w_n$, then the ideal proportional share for VM $i$ is:",
    ),
    (
        "If total distributable credits in an accounting window are `C_total`, then VM `i` receives approximately:",
        r"If total distributable credits in an accounting window are $C_{\text{total}}$, then VM $i$ receives approximately:",
    ),
    # ── Standalone display equations (own line, convert to $$) ───────────────
    ("`share_i = w_i / sum_j w_j`", r"$$\text{share}_i = \frac{w_i}{\sum_j w_j}$$"),
    ("`C_i = C_total * (w_i / sum_j w_j)`", r"$$C_i = C_{\text{total}} \cdot \frac{w_i}{\sum_j w_j}$$"),
    ("`r_i = sum_{j: j->i} r_j / d_j`", r"$$r_i = \sum_{j:\, j \to i} \frac{r_j}{d_j}$$"),
    ("`sum_i r_i = 1`", r"$$\sum_i r_i = 1$$"),
    ("`v_(t+1) = M v_t`", r"$$\mathbf{v}_{t+1} = M\,\mathbf{v}_t$$"),
    ("`||v_t - v_(t-1)|| <= epsilon`", r"$$\|\mathbf{v}_t - \mathbf{v}_{t-1}\| \leq \varepsilon$$"),
    ("`v = d M v + (1-d) * (1/n) * 1`", r"$$\mathbf{v} = d\,M\,\mathbf{v} + (1-d)\,\frac{1}{n}\,\mathbf{1}$$"),
    ("`W + R > N`", r"$$W + R > N$$"),
    ("`(D*E) mod phi(N) = 1`", r"$$D \cdot E \equiv 1 \pmod{\phi(N)}$$"),
    (
        "`R(u) proportional sum_{v in backlinks(u)} R(v) / outdeg(v)`",
        r"$$R(u) \propto \sum_{v \in \text{backlinks}(u)} \frac{R(v)}{\text{outdeg}(v)}$$",
    ),
    # ── Table cell formulas (inline $...$) ───────────────────────────────────
    # AIMD table cells
    ("`W_{t+1} = W_t + alpha`", r"$W_{t+1} = W_t + \alpha$"),
    ("`W <- beta W`", r"$W \leftarrow \beta W$"),
    (
        "`W_avg approximately (W_max + W_max/2)/2 = 3W_max/4`",
        r"$W_{\text{avg}} \approx \frac{W_{\text{max}} + W_{\text{max}}/2}{2} = \frac{3W_{\text{max}}}{4}$",
    ),
    ("`alpha = 1`", r"$\alpha = 1$"),
    ("`beta = 1/2`", r"$\beta = 1/2$"),
    # Fat-tree table cells
    ("`k`", r"$k$"),
    ("`(k/2)^2`", r"$(k/2)^2$"),
    ("`k/2`", r"$k/2$"),
    ("`k^3/4`", r"$k^3/4$"),
    ("`5k^2/4`", r"$5k^2/4$"),
    # SEDF table cells
    ("`d_i`", r"$d_i$"),
    ("`r_i`", r"$r_i$"),
    ("`u_i = s_i / p_i`", r"$u_i = s_i / p_i$"),
    ("`U = sum_i (s_i / p_i)`", r"$U = \sum_i (s_i / p_i)$"),
    ("`sum_i (s_i / p_i) <= 1`", r"$\sum_i (s_i / p_i) \leq 1$"),
    ("`LCM(p_1, p_2, ..., p_n)`", r"$\text{lcm}(p_1, p_2, \ldots, p_n)$"),
    ("`x_i = 0` (NWC)", r"$x_i = 0$ (NWC)"),
    ("`x_i = 1` (WC)", r"$x_i = 1$ (WC)"),
    ("`r_i` resets to `s_i` only at period boundaries", r"$r_i$ resets to $s_i$ only at period boundaries"),
    (
        "When `r_i` hits 0, it can be replenished for extra-time use if VM remains runnable",
        r"When $r_i$ hits 0, it can be replenished for extra-time use if VM remains runnable",
    ),
    # Credit scheduler table cells
    ("`share_i = w_i / sum_j w_j`", r"$\text{share}_i = w_i / \sum_j w_j$"),
    ("`C_i = C_total * w_i / sum_j w_j`", r"$C_i = C_{\text{total}} \cdot w_i / \sum_j w_j$"),
    # High-yield formula sheet rows
    ("`u_i = s_i / p_i`", r"$u_i = s_i / p_i$"),
    ("`sum_i (s_i / p_i) <= 1`", r"$\sum_i (s_i / p_i) \leq 1$"),
    ("`LCM(p_1, ..., p_n)`", r"$\text{lcm}(p_1, \ldots, p_n)$"),
    ("`share_i = w_i / sum_j w_j`", r"$\text{share}_i = w_i / \sum_j w_j$"),
    ("`C_i = C_total * w_i / sum_j w_j`", r"$C_i = C_{\text{total}} \cdot w_i / \sum_j w_j$"),
    # RSA table cells
    ("`CT = PT^E mod N`", r"$CT = PT^E \bmod N$"),
    ("`PT = CT^D mod N`", r"$PT = CT^D \bmod N$"),
    # PageRank formula sheet rows (table cells)
    ("`r_i = sum_{j: j->i} r_j / d_j`", r"$r_i = \sum_{j:\, j \to i} r_j / d_j$"),
    ("`sum_i r_i = 1`", r"$\sum_i r_i = 1$"),
    ("`v_(t+1) = M v_t`", r"$\mathbf{v}_{t+1} = M\,\mathbf{v}_t$"),
    ("`v = d M v + (1-d) * (1/n) * 1`", r"$\mathbf{v} = d\,M\,\mathbf{v} + (1\!-\!d)\,\frac{1}{n}\,\mathbf{1}$"),
    ("`||v_t - v_(t-1)|| <= epsilon`", r"$\|\mathbf{v}_t - \mathbf{v}_{t-1}\| \leq \varepsilon$"),
    # Dynamo formula sheet rows (table cells)
    ("`1 - (1 - p)^n`", r"$1 - (1-p)^n$"),
    ("`W + R > N`", r"$W + R > N$"),
    ("`O(log M)`", r"$O(\log M)$"),
    # ── Bullet-point prose ───────────────────────────────────────────────────
    # AIMD bullets
    (
        "- Flow `i`: `W_i(k+1) = beta_i W_i(k) + (alpha_i / sum_j alpha_j) * sum_j ((1-beta_j)W_j(k))`",
        r"- Flow $i$: $W_i(k+1) = \beta_i W_i(k) + \dfrac{\alpha_i}{\sum_j \alpha_j} \sum_j \bigl(1-\beta_j\bigr)W_j(k)$",
    ),
    (
        "- Steady-state fairness direction: `W_i* proportional alpha_i / (1-beta_i)`",
        r"- Steady-state fairness direction: $W_i^* \propto \dfrac{\alpha_i}{1-\beta_i}$",
    ),
    (
        "- If all flows use `alpha_i = 1, beta_i = 1/2`, then fair equilibrium is equal windows.",
        r"- If all flows use $\alpha_i = 1,\; \beta_i = 1/2$, then fair equilibrium is equal windows.",
    ),
    ("- Start `W = 10` MSS, `alpha = 1`, `beta = 1/2`", r"- Start $W = 10$ MSS, $\alpha = 1$, $\beta = 1/2$"),
    ("- After 3 RTTs without congestion: `W = 13`", r"- After 3 RTTs without congestion: $W = 13$"),
    (
        "- Congestion occurs: `W <- 13/2 = 6.5` MSS (implementation rounds by stack rules)",
        r"- Congestion occurs: $W \leftarrow 13/2 = 6.5$ MSS (implementation rounds by stack rules)",
    ),
    # Fat-tree derivation bullets
    ("- Assume `k` is even and every switch has `k` ports.", r"- Assume $k$ is even and every switch has $k$ ports."),
    ("    - Edge switches = `k/2`", r"    - Edge switches = $k/2$"),
    ("    - Aggregation switches = `k/2`", r"    - Aggregation switches = $k/2$"),
    ("    - Hosts per edge = `k/2`", r"    - Hosts per edge = $k/2$"),
    ("    - Hosts per pod = `(k/2) * (k/2) = k^2/4`", r"    - Hosts per pod = $(k/2) \times (k/2) = k^2/4$"),
    ("- Total hosts across `k` pods:", r"- Total hosts across $k$ pods:"),
    ("    - `N_hosts = k * (k^2/4) = k^3/4`", r"    - $N_{\text{hosts}} = k \times (k^2/4) = k^3/4$"),
    ("    - `N_core = (k/2)^2 = k^2/4`", r"    - $N_{\text{core}} = (k/2)^2 = k^2/4$"),
    ("    - Pod switches = `k * (k/2 + k/2) = k^2`", r"    - Pod switches = $k \times (k/2 + k/2) = k^2$"),
    ("    - `N_total = k^2 + k^2/4 = 5k^2/4`", r"    - $N_{\text{total}} = k^2 + k^2/4 = 5k^2/4$"),
    (
        "- Edge-aggregation links per pod: `(k/2)*(k/2) = k^2/4`",
        r"- Edge-aggregation links per pod: $(k/2) \times (k/2) = k^2/4$",
    ),
    (
        "- Total edge-aggregation links: `k * (k^2/4) = k^3/4`",
        r"- Total edge-aggregation links: $k \times (k^2/4) = k^3/4$",
    ),
    ("- Total aggregation-core links: also `k^3/4`", r"- Total aggregation-core links: also $k^3/4$"),
    # Fat-tree worked example
    ("Worked example (`k = 8`):", r"Worked example ($k = 8$):"),
    ("- Pods = `8`", r"- Pods = $8$"),
    ("- Edge per pod = `4`, Aggregation per pod = `4`", r"- Edge per pod = $4$, Aggregation per pod = $4$"),
    ("- Hosts per edge = `4`", r"- Hosts per edge = $4$"),
    ("- Hosts per pod = `4*4 = 16`", r"- Hosts per pod = $4 \times 4 = 16$"),
    (
        "- Total hosts = `8*16 = 128` (matches `k^3/4 = 8^3/4 = 128`)",
        r"- Total hosts = $8 \times 16 = 128$ (matches $k^3/4 = 8^3/4 = 128$)",
    ),
    ("- Core switches = `(8/2)^2 = 16`", r"- Core switches = $(8/2)^2 = 16$"),
    ("- Total switches = `5*8^2/4 = 80`", r"- Total switches = $5 \times 8^2/4 = 80$"),
    ("Small construction example (`k = 4`):", r"Small construction example ($k = 4$):"),
    ("- Core: `(4/2)^2 = 4`", r"- Core: $(4/2)^2 = 4$"),
    ("- Hosts per edge: `2`, total hosts `= 4^3/4 = 16`", r"- Hosts per edge: $2$, total hosts $= 4^3/4 = 16$"),
    (
        "- If your constructed topology does not satisfy `hosts = k^3/4` and `core = (k/2)^2`, re-check pod and core-group wiring.",
        r"- If your constructed topology does not satisfy $\text{hosts} = k^3/4$ and $\text{core} = (k/2)^2$, re-check pod and core-group wiring.",
    ),
    # Fat-tree must-memorize bullet
    (
        "5. Fat-tree with k-port switches supports `k^3/4` hosts.",
        r"5. Fat-tree with $k$-port switches supports $k^3/4$ hosts.",
    ),
    # SEDF description bullets
    (
        "SEDF models each VM request as tuple `(s_i, p_i, x_i)`:",
        r"SEDF models each VM request as tuple $(s_i, p_i, x_i)$:",
    ),
    ("- `s_i`: CPU time requested per period", r"- $s_i$: CPU time requested per period"),
    ("- `p_i`: period length", r"- $p_i$: period length"),
    (
        "- `x_i`: extra-time flag (`1` = can consume slack in WC mode, `0` = no extra)",
        r"- $x_i$: extra-time flag ($1$ = can consume slack in WC mode, $0$ = no extra)",
    ),
    # SEDF scheduling rule bullets
    (
        "- At each slot, among runnable VMs with `r_i > 0`, run VM with earliest deadline `d_i`.",
        r"- At each slot, among runnable VMs with $r_i > 0$, run VM with earliest deadline $d_i$.",
    ),
    # SEDF worked example bullets
    ("- VM1: `(1,2,0)` => `u_1 = 1/2 = 0.5`", r"- VM1: $(1,2,0)$ $\Rightarrow$ $u_1 = 1/2 = 0.5$"),
    (
        "- VM2: `(2,7,0)` => `u_2 = 2/7 approximately 0.286`",
        r"- VM2: $(2,7,0)$ $\Rightarrow$ $u_2 = 2/7 \approx 0.286$",
    ),
    (
        "- `U = 0.5 + 0.286 = 0.786 <= 1` -> schedulable",
        r"- $U = 0.5 + 0.286 = 0.786 \leq 1$ $\rightarrow$ schedulable",
    ),
    ("- Hyperperiod `= LCM(2,7) = 14`", r"- Hyperperiod $= \text{lcm}(2,7) = 14$"),
    # Credit scheduler inline bullets
    ("- Shares: VM1 = `1/3`, VM2 = `2/3`", r"- Shares: VM1 = $1/3$, VM2 = $2/3$"),
    # Credit scheduler policy row (table)
    ("| Deadline + reservation tuple `(s,p,x)` |", r"| Deadline + reservation tuple $(s,p,x)$ |"),
    ("| Yes (`x_i`) |", r"| Yes ($x_i$) |"),
    # Exam workflow bullets referencing SEDF
    (
        "1. Convert each VM requirement into utilization (`s_i/p_i`).",
        r"1. Convert each VM requirement into utilization ($s_i/p_i$).",
    ),
    (
        "3. Compute `LCM` of periods to determine repeating schedule window.",
        r"3. Compute $\text{lcm}$ of periods to determine repeating schedule window.",
    ),
    # Must-memorize SEDF bullet
    (
        "3. SEDF tuple `(s_i, p_i, x_i)` is the key abstraction.",
        r"3. SEDF tuple $(s_i, p_i, x_i)$ is the key abstraction.",
    ),
    # Diffie-Hellman bullets
    ("- Alice picks secret `a`, sends `A = g^a mod p`", r"- Alice picks secret $a$, sends $A = g^a \bmod p$"),
    ("- Bob picks secret `b`, sends `B = g^b mod p`", r"- Bob picks secret $b$, sends $B = g^b \bmod p$"),
    ("- Alice computes `s = B^a mod p`", r"- Alice computes $s = B^a \bmod p$"),
    ("- Bob computes `s = A^b mod p`", r"- Bob computes $s = A^b \bmod p$"),
    ("- Both get same shared secret: `s = g^(ab) mod p`", r"- Both get same shared secret: $s = g^{ab} \bmod p$"),
    (
        "- Attacker sees `p, g, A, B`, but recovering `a` or `b` is hard for large parameters (discrete log hardness).",
        r"- Attacker sees $p, g, A, B$, but recovering $a$ or $b$ is hard for large parameters (discrete log hardness).",
    ),
    # RSA key gen bullets
    ("1. Choose primes `P, Q`", r"1. Choose primes $P, Q$"),
    ("2. Compute `N = P*Q`", r"2. Compute $N = P \cdot Q$"),
    ("3. Compute `phi(N) = (P-1)(Q-1)`", r"3. Compute $\phi(N) = (P-1)(Q-1)$"),
    (
        "4. Choose public exponent `E` with `gcd(E, phi(N)) = 1`",
        r"4. Choose public exponent $E$ with $\gcd(E, \phi(N)) = 1$",
    ),
    ("5. Choose private exponent `D` such that:", r"5. Choose private exponent $D$ such that:"),
    # PageRank graph notation bullets
    (
        "- Directed edge `j -> i` = page `j` links to page `i`",
        r"- Directed edge $j \to i$ means page $j$ links to page $i$",
    ),
    ("- `B_i`: set of backlinks to page `i`", r"- $B_i$: set of backlinks to page $i$"),
    (
        "- `d_j`: out-degree (number of outgoing links) of page `j`",
        r"- $d_j$: out-degree (number of outgoing links) of page $j$",
    ),
    ("- `r_i` or `v_i`: PageRank score of node `i`", r"- $r_i$ or $v_i$: PageRank score of node $i$"),
    # PageRank prose inline
    (
        "- Page `i` receives rank mass from pages linking to it.",
        r"- Page $i$ receives rank mass from pages linking to it.",
    ),
    (
        "- Each source page splits its mass equally among its outgoing links.",
        "- Each source page splits its mass equally among its outgoing links.",
    ),
    # PageRank matrix bullets
    ("Let `M` be transition matrix, where:", r"Let $M$ be the transition matrix, where:"),
    ("- `M_ij = 1/d_j` if `j -> i`, else `0`", r"- $M_{ij} = 1/d_j$ if $j \to i$, else $0$"),
    ("- Columns sum to 1 for column-stochastic form.", "- Columns sum to 1 for column-stochastic form."),
    # PageRank damping prose
    (
        "Use damping factor `d` and teleport distribution (often uniform):",
        r"Use damping factor $d$ and teleport distribution (often uniform):",
    ),
    ("- With probability `d`, follow a link.", r"- With probability $d$, follow a link."),
    ("- With probability `1-d`, jump to random page.", r"- With probability $1-d$, jump to random page."),
    (
        "- `d` in range about `0.8` to `0.9` (commonly around `0.85`).",
        r"- $d$ is in range about $0.8$ to $0.9$ (commonly around $0.85$).",
    ),
    # PageRank worked example bullets
    ("2. Construct transition matrix `M`.", r"2. Construct transition matrix $M$."),
    ("3. Initialize `v_0 = (1/n) * 1`.", r"3. Initialize $\mathbf{v}_0 = (1/n)\,\mathbf{1}$."),
    (
        "4. If damping is required, iterate using `v_(t+1) = d M v_t + (1-d)(1/n)1`.",
        r"4. If damping is required, iterate using $\mathbf{v}_{t+1} = d\,M\,\mathbf{v}_t + (1-d)\frac{1}{n}\mathbf{1}$.",
    ),
    ("6. Rank pages by final `v` entries.", r"6. Rank pages by final $\mathbf{v}$ entries."),
    # MapReduce notation
    ("- `map(k, v) -> list(k2, v2)`", r"- $\text{map}(k, v) \to \text{list}(k_2, v_2)$"),
    ("- `reduce(k2, list(v2)) -> list(k3, v3)`", r"- $\text{reduce}(k_2, \text{list}(v_2)) \to \text{list}(k_3, v_3)$"),
    ("1. Split input into `M` shards", r"1. Split input into $M$ shards"),
    ("4. Run `R` reduce tasks", r"4. Run $R$ reduce tasks"),
    ("5. Write outputs (`R` output files)", r"5. Write outputs ($R$ output files)"),
    ("Why `M >> workers`:", r"Why $M \gg \text{workers}$:"),
    # MapReduce table cells
    (
        "| `M` | Number of map tasks | Choose `M` much larger than worker count |",
        r"| $M$ | Number of map tasks | Choose $M$ much larger than worker count |",
    ),
    (
        "| `R` | Number of reduce tasks | Usually smaller than `M` |",
        r"| $R$ | Number of reduce tasks | Usually smaller than $M$ |",
    ),
    # Word count example bullets
    ("For each word `w` in input record, emit `(w, 1)`.", r"For each word $w$ in the input record, emit $(w, 1)$."),
    (
        "For each key `w`, sum all counts and emit `(w, total)`.",
        r"For each key $w$, sum all counts and emit $(w, \text{total})$.",
    ),
    (
        "- Emit `(PageRank, URL)` and leverage framework sorting.",
        r"- Emit $(\text{PageRank}, \text{URL})$ and leverage framework sorting.",
    ),
    # Consistent hashing bullets
    ("Mapping: `node = hash(key) mod k`", r"Mapping: $\text{node} = \text{hash}(\text{key}) \bmod k$"),
    (
        "- If `k` changes (node join/failure), many keys remap globally.",
        r"- If $k$ changes (node join/failure), many keys remap globally.",
    ),
    (
        "- Map both nodes and keys to a ring over ID space `0 .. 2^m - 1`.",
        r"- Map both nodes and keys to a ring over ID space $[0,\; 2^m - 1]$.",
    ),
    # Key-value store bullets
    ("- `put(key, value)`", r"- $\text{put}(\text{key},\, \text{value})$"),
    ("- `get(key)`", r"- $\text{get}(\text{key})$"),
    # Quorum bullets
    ("- `N` = replication factor (replicas per key)", r"- $N$ = replication factor (replicas per key)"),
    ("- `W` = write quorum (acks needed)", r"- $W$ = write quorum (acks needed)"),
    ("- `R` = read quorum (responses needed)", r"- $R$ = read quorum (responses needed)"),
    ("- `N=3, W=2, R=2` satisfies overlap.", r"- $N=3, W=2, R=2$ satisfies overlap."),
    # Dynamo ring/routing bullets
    (
        "- Each node stores routing info about only `O(log M)` nodes (M = total nodes).",
        r"- Each node stores routing info about only $O(\log M)$ nodes ($M$ = total nodes).",
    ),
    ("- Route lookup in `O(log M)` hops.", r"- Route lookup in $O(\log M)$ hops."),
    (
        "- Periodic `stabilize()` and `notify()` maintain successor/predecessor correctness after joins/leaves.",
        r"- Periodic $\texttt{stabilize()}$ and $\texttt{notify()}$ maintain successor/predecessor correctness after joins/leaves.",
    ),
    (
        "- Maintain multiple successors (`k > 1`) for robustness.",
        r"- Maintain multiple successors ($k > 1$) for robustness.",
    ),
    # Dynamo must-memorize bullet
    (
        "4. Quorum reads/writes use `N, W, R` and overlap condition `W + R > N`.",
        r"4. Quorum reads/writes use $N, W, R$ and overlap condition $W + R > N$.",
    ),
    # Interface bullets
    ("- `get(key) -> value(s), context`", r"- $\text{get}(\text{key}) \to \text{value(s)},\, \text{context}$"),
    (
        "- `put(key, context, value) -> OK`",
        r"- $\text{put}(\text{key},\, \text{context},\, \text{value}) \to \text{OK}$",
    ),
    ("- `get` may return multiple conflicting versions.", r"- $\text{get}$ may return multiple conflicting versions."),
    (
        "- `context` carries version metadata (for causality/merge handling).",
        r"- $\text{context}$ carries version metadata (for causality/merge handling).",
    ),
    # Dynamo formula sheet table rows
    ("| `1 - (1 - p)^n` |", r"| $1 - (1-p)^n$ |"),
    ("| `W + R > N` |", r"| $W + R > N$ |"),
    ("| `O(log M)` state and lookup hops |", r"| $O(\log M)$ state and lookup hops |"),
    ("| key -> first clockwise successor |", r"| key $\to$ first clockwise successor |"),
]

# Process each file
for filename in FILES:
    if not os.path.exists(filename):
        print(f"SKIP (not found): {filename}")
        continue

    with open(filename, "r", encoding="utf-8") as f:
        text = f.read()

    changed = 0
    for old, new in EXACT:
        if old in text:
            text = text.replace(old, new)
            changed += 1

    with open(filename, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"Done: {filename} ({changed} substitutions applied)")

print("\nAll files processed.")
