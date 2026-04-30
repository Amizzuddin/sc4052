# Lecture 6B Summary: Crowdsourcing in Cloud

![Crowdsourcing concept map](crowdsourcing_concept_map.jpg)

## 1. Big Picture
Crowdsourcing in cloud computing uses large numbers of distributed humans to solve tasks that are still difficult for fully automated AI systems.

Core idea:
- Human-assisted computation = combine cloud-scale coordination with human judgment.

## 2. Why Crowdsourcing Matters
| Motivation | Explanation |
|---|---|
| AI limitations | Some perception/language tasks are easier for humans than machines |
| Massive scale | Internet enables millions of contributors to work on microtasks |
| Speed and flexibility | Tasks can be split and processed in parallel |
| Data generation | Human answers can train or improve ML/AI systems |

## 3. Human-in-the-Loop Concept
| Component | Role |
|---|---|
| Task requester | Defines task and quality requirements |
| Crowd workers/users | Perform microtasks (label, verify, translate, annotate) |
| Platform | Distributes tasks and collects responses |
| Aggregation logic | Combines responses into final output |
| Quality control | Redundancy, agreement, filtering, trust mechanisms |

## 4. Historical and Modern Context
| Story | Significance |
|---|---|
| Mechanical Turk (18th century) | Early symbolic example of “human hidden behind automation” |
| Amazon Mechanical Turk (2005) | Cloud marketplace for on-demand human micro-work |
| CAPTCHA/reCAPTCHA | Uses human effort for both bot filtering and useful labeling/digitization |

## 5. CAPTCHA and reCAPTCHA Insights
| Aspect | Key point |
|---|---|
| CAPTCHA purpose | Distinguish humans from bots (challenge-response) |
| Adversarial reality | CAPTCHA sweatshops can bypass pure automation defenses |
| reCAPTCHA contribution | Redirects human effort to useful tasks (e.g., OCR ambiguity resolution) |
| Design challenge | Must remain easy for humans but hard for automated attacks |

Exam memory line:
- Good crowdsourcing tasks align human effort with platform utility.

## 6. Games With a Purpose (GWAP): ESP Game
| Feature | Description |
|---|---|
| Setup | Two players view same image but cannot communicate |
| Objective | Type the same word independently |
| Output | Agreed words become image labels |
| Value | Converts gameplay into structured annotation data |

## 7. Crowdsourcing Application Cases from Lecture
| Application | Human task | Output value |
|---|---|---|
| OCR and book digitization | Resolve unreadable scanned words | Higher text accuracy |
| Language translation (e.g., app-based) | Translate phrases/sentences | Scalable multilingual content |
| Duolingo-style language tasks | Answer short exercises | Learning + data generation loop |
| Autograding (education chatbot) | Image annotation / response labeling | Assist grading at scale |
| Collective decision systems | Group input + discussion + voting | Strong aggregate performance (wisdom of crowd) |

## 8. Wisdom of the Crowd
Lecture example: Kasparov vs The World (1999 online chess).

Takeaway:
- A coordinated crowd, with discussion and expert/computer support, can produce high-quality collective decisions even against elite individuals.

## 9. Design Dimensions for Crowdsourcing Systems (Exam Table)
| Dimension | Typical options | Tradeoff |
|---|---|---|
| Task granularity | Coarse task vs microtask | Smaller tasks scale better but need stronger aggregation |
| Incentive model | Monetary, gamification, leaderboard, learning value | Cost vs engagement quality |
| Quality assurance | Majority vote, redundancy, gold questions, reputation | Accuracy vs latency/cost |
| Latency sensitivity | Real-time vs batch | Speed vs reliability |
| Privacy/ethics | Open task data vs protected handling | Utility vs compliance/risk |

## 10. Advantages and Limitations
| Advantages | Limitations / Risks |
|---|---|
| Handles tasks hard for current AI | Noisy or malicious worker responses |
| Scales globally using cloud platforms | Quality control overhead |
| Can generate labeled data for ML | Potential bias in crowd responses |
| Flexible and fast for many domains | Privacy/security concerns in sensitive tasks |
| Can reduce cost vs expert-only workflows | Incentive manipulation and adversarial behavior |

## 11. Typical Pipeline (Exam-Ready)
1. Decompose problem into microtasks.
2. Publish tasks to crowd platform.
3. Collect multiple responses per item.
4. Apply quality control (agreement checks, filtering, confidence).
5. Aggregate outputs into final prediction/annotation.
6. Optionally feed results back to improve AI models.

## 12. Must-Memorize Points
1. Crowdsourcing is a core human-assisted computation paradigm in cloud systems.
2. Cloud provides the coordination and scale; humans provide perception/judgment.
3. CAPTCHA/reCAPTCHA shows challenge-response can be repurposed for useful data tasks.
4. GWAP converts human entertainment into data labeling.
5. Practical success depends on incentives, quality control, and aggregation design.
6. Crowdsourcing complements AI rather than simply replacing it.
