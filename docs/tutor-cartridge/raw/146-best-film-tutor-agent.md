---
title: "Architecture of an Experiential Film-Studies Tutor: Cognitive Engineering, Desirable Difficulties, and Progressive Disclosure in Aesthetic Education"
type: deep-research
extraction: flat-research-report
sources_found: 46
created: 2026-09-10
tags: []
origin_repo: praxis-halo
origin_path: raw/146-best-film-tutor-agent.md
origin_sha256: 2eba4b055baef928118c9d5ab6e246847698b1b8d1dbcd7d8ad1d588874accb4
scrub_rules: handoff/scrub-rules/146.rules
scrub_rules_sha256: 1301f1e9c7b408b1802f9ffe65fb12cbd0001c4c91bea16057aad29cd426336d
scrubbed_on: 2026-09-13
handoff_bundle: 2026-09-13-movie-brain-cartridge
derivative: scrubbed
origin_id: 146
---

# Architecture of an Experiential Film-Studies Tutor: Cognitive Engineering, Desirable Difficulties, and Progressive Disclosure in Aesthetic Education

## Theoretical Foundations of Expert Tutoring Systems

### Bloom's Two-Sigma and the Socratic Tutoring Paradigm Achieving human-expert tutoring performance requires a departure from conventional, lecture-based instructional designs. The two-sigma problem demonstrates that students who receive individual tutoring perform two standard deviations above those in conventional classrooms . This performance gap is not driven by simple content delivery, but by the dynamic, conversational, and highly personalized nature of one-on-one dialogue .

To replicate these learning gains in a computational system, the architecture must move away from the typical patterns of generic chatbots. Instead, it must implement a rigorous Socratic model that acts as a challenging conversational partner . Rather than providing answers or correcting errors directly, the system guides the student to discover core concepts through effortful dialogue and self-explanation .

### Chi's ICAP Framework in Visual-Sensory Analysis The cognitive engagement of the learner is governed by the Interactive-Constructive-Active-Passive (ICAP) framework, which outlines a clear taxonomy of learning activities . This taxonomy predicts that interactive learning activities yield deeper understanding than constructive ones, which in turn outperform active and passive modes .

| Engagement Mode | Cognitive Definition | Visual-Sensory Implementation | Empirical Validation |
| :--- | :--- | :--- | :--- |
| **Passive** | Storing received information without actively transforming or manipulating it . | Watching a film sequence or listening to pre-recorded cinematic commentary . | Associated with the lowest levels of conceptual retention and transfer . |
| **Active** | Manipulating the physical materials of the learning task without adding new conceptual content . | Pausing playback, taking reproductive, verbatim notes of dialogue, or highlighting visual frames . | Offers marginal improvements over passive viewing but fails to support deep structural analysis . |
| **Constructive** | Generating self-explanations, drawing inferences, and making conceptual connections that go beyond the provided material . | Formulating independent theories of visual style, writing elaborative notes, or drawing stylistic comparisons . | Enhances learning by forcing active schema construction and long-term retention . |
| **Interactive** | Engaging in Socratic, co-constructive dialogue with an expert or peer around a shared learning task . | Exchanging visual hypotheses with the tutor, defending interpretations, and collaboratively analyzing scene dynamics . | Generates the highest learning gains, with a six-fold performance increase over passive modes . |

For a learner with a trained eye from an adjacent craft, passive exposure to film theory does not translate into a practical mastery of the craft. Deep learning occurs when the user is forced to transition from active visual observation to constructive analysis, culminating in an interactive Socratic dialogue .

This interactive exchange must focus on elaborative note-taking and conceptual inference, which are highly correlated with successful inquiry performance, rather than simple reproductive recall .

### Lepper's Motivational Tactics for Analytical Autonomy To sustain high levels of cognitive effort, the tutoring system must incorporate intrinsic motivational strategies . Expert tutors cultivate motivation by balancing challenge, curiosity, control, and confidence . This balance is achieved through several core principles:

* **Autonomy and Personal Control**: The system fosters a sense of personal control by allowing the user to select which films to study, determine the pace of the discussion, and guide the focus of the dialogue . The tutor must avoid unsolicited interventions, which can undermine the user's feelings of independence and self-regulation .
* **Cognitive Curiosity**: The tutor stimulates curiosity by pointing out structural inconsistencies, omissions, or visual paradoxes in the user's analyses, prompting them to resolve these gaps themselves .
* **Personalization and Context**: The tutor contextualizes its feedback by aligning visual analyses with the user's established domain expertise—using sensory terminology from the learner's adjacent crafts, such as tasting vocabularies or technical image-making concepts .
* **Empathetic Praise and Effort Focus**: Feedback from the tutor focuses on the user's analytical effort and methodology rather than raw performance, which helps sustain self-esteem and self-efficacy when tackling complex aesthetic judgments .

These motivational strategies are woven into the Socratic dialogue using specific verbal cues that evoke novelty, utility, applicability, anticipation, surprise, and challenge . This approach keeps the user highly engaged in the analytical process .

### Contingent Scaffolding in the Zone of Proximal Development To ensure the Socratic dialogue remains supportive yet challenging, the tutor uses contingent scaffolding . Originating from the theories of Wood, Bruner, and Ross, scaffolding is a dynamic process that allows a learner to solve problems that would otherwise be just beyond their independent capacity . This approach is governed by two main principles:

* **Contingency**: The tutor adjusts its support based on the user's ongoing performance within their Zone of Proximal Development (ZPD) . High challenge must be matched with high support to prevent frustration, while low challenge must be balanced with low support to avoid boredom .
* **Fading**: As the user demonstrates a stronger grasp of specific cinematic styles, the tutor systematically reduces its support, encouraging greater analytical independence and student agency .

This scaffolding must be responsive to the immediate, unplanned needs of the user during dialogue, ensuring the system adapts to their unique learning pace .

### Graesser's AutoTutor and Conversational Dialogue Engines The dialogue engine is modeled on the Expectation-Misconception Tailored (EMT) framework developed for AutoTutor . Rather than evaluating student input via strict keyword matching, the system uses semantic similarity models to compare the user's natural language contributions with a set of pre-defined expectations and common misconceptions .

The conversation is managed as an augmented state transition network via a Dialogue Action Network (DAN), which determines the tutor's next conversational move based on the history of the dialogue . The engine operates using a specific suite of conversational moves designed to guide the user toward key expectations:

* **Dialogue Pumps**: Open-ended prompts designed to elicit further unstructured analysis (e.g., "What else do you observe about this sequence?") .
* **Dialogue Hints**: Contextual prompts that direct attention to a specific visual or technical area without revealing the answer (e.g., "Consider the direction of the key light on the subject.") .
* **Dialogue Prompts**: Highly targeted queries that require the user to fill in a specific terminology or conceptual gap (e.g., "This shallow depth of field is a characteristic feature of an ______ lens configuration.") .
* **Assertions**: Direct explanations of the target concept, used only when all other scaffolding attempts have been exhausted .

To encourage active retrieval and constructive reasoning, the tutor prioritizes open-ended pumps and hints over direct prompts and assertions, as these are more strongly correlated with deep conceptual learning .

Additionally, the dialogue engine must handle metacognitive statements from the user (e.g., "I don't understand" or "I'm confused") by providing encouraging, supportive prompts that help them articulate what they *do* know, keeping the conversation on track .

---

## Desirable Difficulties in Aesthetic and Sensory Domains

### The Generation Effect and Sealed Recall To prevent passive learning and ensure the tutor does not inadvertently lead the user's observations, the system operates under a strict "sealed recall" protocol. The agent never initiates discussion on a scene or film. The learner must initiate the interaction by providing their initial, unprompted analysis of the visual sequence.

This requirement forces the user to actively retrieve and synthesize conceptual connections from memory rather than simply recognizing visual cues pointed out by the tutor . This initial analysis is then locked in as the baseline profile for the session, ensuring that all subsequent dialogue is anchored to the user's independent observations.

### The Hypercorrection Effect in Visual Judgment The hypercorrection effect describes a cognitive phenomenon where errors made with high confidence, once corrected, are retained far better than low-confidence errors . This effect is highly relevant for a learner with established expert sensory schemas from an adjacent craft.

When the user makes a confident but incorrect stylistic claim—such as misidentifying a lens's focal length or misattributing a camera movement—the tutor does not offer immediate correction. Instead, it guides the user to re-examine the visual evidence, creating a prediction error. Correcting these highly confident errors leads to a significant and memorable update to the user's analytical framework .

### Delayed Feedback and Analytical Independence Immediate error correction can disrupt the flow of analysis and reduce the learner's sense of control . Therefore, the tutor delays detailed feedback until the learner has completed their initial analysis of the scene . This delay gives the learner the opportunity to self-correct as they articulate their thoughts, while also ensuring that the feedback is integrated into a complete conceptual structure .

### Interleaving across the Cinematic Canon Rather than analyzing the 150-film canon in a standard chronological or director-specific sequence, the tutor structures the curriculum using interleaving . The system alternates between different historical eras, directors, and aesthetic styles (e.g., moving from French New Wave editing paradigms to American Film Noir lighting configurations).

This approach prevents the learner from relying on a single interpretive frame . Interleaved practice trains the user's ability to distinguish subtle visual patterns, ensuring they can apply craft vocabulary accurately across a wide range of cinematic styles .

---

## Progressive Disclosure Knowledge Architecture

To prevent sycophancy, avoid leading the user, and support an audio-first, accessibility-aware learning process, the system's knowledge is split into three distinct, insulated tiers. This progressive disclosure model ensures that the agent cannot generate pre-authored insights or confirm the user's claims without verifying them against an immutable record.

```
+-------------------------------------------------------------------------------
--+
| TIER 1: GLOBAL ONTOLOGICAL & PERSONAL METADATA
|
| - Cinematic Flavor-Wheel Tree (Hierarchical Visual and Sensory Vocabulary)
|
| - Historical Stylistic Lexicon (Formal Movements, Apparatus Specs)
|
| - Learner Profile (Audio-First Cadence, Accessibility Support, Calibration
Log)  |
+-------------------------------------------------------------------------------
--+
                                      |
                                      v
+-------------------------------------------------------------------------------
--+
| TIER 2: FILM-SPECIFIC MASTER TEMPLATE (IMMUTABLE DATABASE)
|
| - Ground-Truth Scene Metadata (Timestamps, Spatial Maps, Key Craft Attributes)
|
| - Structural Expectations & Common Aesthetic Misconceptions
|
| - Pairwise Film Relationships (Interleaving Triggers)
|
+-------------------------------------------------------------------------------
--+
                                      |
                       [Triggered by Sealed Recall]
                                      v
+-------------------------------------------------------------------------------
--+
| TIER 3: ACTIVE SESSION DIALOGUE STATE
|
| - Sealed User Analysis (Locked Visual & Narrative Observations)
|
| - Active Micro-Socratic Scaffolding State (Current Pump/Hint/Prompt State)
|
| - Calibration Assessment Cache (Real-Time Probability Predictions)
|
+-------------------------------------------------------------------------------
--+
```

### Tier 1: Global Ontological and Personal Metadata This tier contains the foundational database of cinematic theory and the user's learning profile. It does not contain information about the specific film under review .

* **The Cinematic Flavor-Wheel Tree**: A non-numeric taxonomy of sensory characteristics (analogous to coffee or spirits tasting ) that replaces traditional multi-axis scorecards. This allows the user to classify compositions by visual characteristics (e.g., "high-contrast chiaroscuro," "anamorphic fall-off," "deep-focus depth") without assigning arbitrary numerical ratings, which can cause psychometric resistance and cognitive fatigue.
* **The Historical Stylistic Lexicon**: Definitions of formal movements, apparatus specifications, and director-specific techniques.
* **The Learner Profile**: Tracks the user's historical strengths, calibration curves, preferences for an audio-first cadence, and accommodations for text-processing needs.

### Tier 2: Film-Specific Master Template This tier contains an immutable record of the film being studied. It is completely insulated from the active conversation until specific criteria are met.

* **Ground-Truth Metadata**: Exact scene-by-scene cataloging of edit rates, camera setups, lens choices, lighting designs, and narrative beats.
* **Expectations and Misconceptions**: Standard aesthetic expectations and common misinterpretations associated with each sequence .
* **Comparative Heats Index**: Pre-configured pairings that link specific scenes in the current film to other entries in the 150-film canon to facilitate comparative analysis.

### Tier 3: Active Session Dialogue State This tier is dynamic and transient, holding the state of the active learning session .

* **Sealed User Recall**: The immutable record of the user's initial observations for the current sequence, captured before any tutor input.
* **Active Conversational Metrics**: The current position in the Socratic scaffolding loop (e.g., active expectations met, outstanding misconceptions, and the current level of scaffolding: pump, hint, or prompt) .
* **Real-Time Calibration Cache**: Stored probability predictions and outcomes used to calculate calibration accuracy.

### The Decoupled Examiner Protocol To enforce the principle that the examiner must not author the prose it examines, the system divides these roles between two separate agents: the **Ontological Examiner** and the **Conversational Tutor**.

The Ontological Examiner evaluates the user's sealed recall against the ground truth in Tier 2 to identify gaps and misconceptions. It then passes these raw evaluation coordinates (e.g., a structured data file containing identified gaps and misconceptions) to the Conversational Tutor.

The Conversational Tutor uses this structured data to generate the Socratic dialogue, pumps, and hints, without having direct access to the raw ground-truth descriptions. This separation prevents the tutor from prematurely revealing the correct answers and ensures its responses are driven entirely by the user's contributions.

---

## System Performance Evaluation, Calibration, and Safeguards

Evaluating the tutor's performance requires a clear distinction between process metrics and outcome metrics. Process metrics assess the quality of the immediate interaction, while outcome metrics measure long-term analytical development.

### Process versus Outcome Telemetry

| Performance Metric | Evaluation Domain | Formula / Operationalization | Success Threshold |
| :--- | :--- | :--- | :--- |
| **User-to-Agent Talk Ratio** | Process Dynamics | $\frac{\text{Word Count}_{\text{User}}}{\text{Word Count}_{\text{Agent}}}$ | $\ge 2.5 : 1$ (Ensuring constructive user engagement)  |
| **Socratic Scaffolding Ratio** | Process Quality | $\frac{\text{Pumps} + \text{Hints}}{\text{Prompts} + \text{Assertions}}$ | $\ge 3.0$ (Prioritizing low-support interventions)  |
| **Sycophancy Score** | Safeguards | Number of non-constructive praise statements per session | $0.0$ (Adhering to objective, neutral feedback)  |
| **Unvalidated Claim Rate** | Accuracy | Number of user claims accepted without metadata verification | $0.0$ (Guarding against hallucinated details)  |
| **Brier Score ($BS$)** | Outcome (Calibration) | $BS = \frac{1}{N} \sum (P_i - Y_i)^2$  | $\le 0.15$ (Indicating skilled forecasting calibration)  |
| **Balanced Brier Score ($BBS$)** | Outcome (Calibration) | $BBS = \frac{1}{2} \left[ \frac{\sum_{i \in S_1} (P_i - 1)^2}{N_1} + \frac{\sum_{j \in S_0} (P_j - 0)^2}{N_0} \right]$  | $\le 0.15$ (Isolating calibration on low-prevalence errors)  |

### Brier Score Calibration and the Predict-Before-Reveal Protocol To train visual discrimination, the tutor uses a "predict-before-reveal" protocol. Before a critical visual technique is shown or a key edit is analyzed, the user must estimate the probability ($P \in [0, 1]$) of a specific craft outcome (e.g., "What is the probability that the next sequence uses a match cut to transition between locations?").

The accuracy of these predictions is assessed using the Brier Score ($BS$), a proper scoring rule that penalizes both overconfidence and excessive caution . The score is calculated as:

$$BS = \frac{1}{N} \sum_{i=1}^{N} (P_i - Y_i)^2$$

where $P_i$ represents the user's predicted probability, $Y_i$ is the binary outcome ($1$ if the event occurs, $0$ if not), and $N$ is the total number of predictions .

A Brier Score of $0.00$ indicates perfect prediction accuracy, while a score of $0.25$ represents performance equivalent to random guessing . The system's objective is to help the user achieve a Brier Score below $0.15$ (reflecting skilled forecasting) and eventually below $0.10$ (exceptional calibration) over the course of the 150-film curriculum .

To prevent the calibration score from being distorted during highly accurate runs, the system also calculates the Balanced Brier Score ($BBS$) . This metric adjusts for class imbalance by separately weighting correct and incorrect outcomes within confidence bins, ensuring that calibration remains accurate even when predicting highly common cinematic techniques :

$$BBS = \frac{1}{2} \left[ \frac{\sum_{i \in S_1} (P_i - 1)^2}{N_1} + \frac{\sum_{j \in S_0} (P_j - 0)^2}{N_0} \right]$$

where $S_1$ and $S_0$ are the sets of positive and negative outcomes, and $N_1$ and $N_0$ represent their respective counts .

This calibration metric measures two related properties: calibration (the agreement between predicted probabilities and observed frequencies) and resolution (the ability to distinguish between different rates of outcomes) .

A model that always predicts the base rate may be calibrated overall but provides little case-specific information . Conversely, the Balanced Brier Score ensures that the user is rewarded for making bold, accurate predictions while penalizing overconfident errors .

### Sycophancy Mitigation and Hallucination Controls Sycophancy—the tendency of language models to confirm erroneous claims made by the user—is a significant barrier to effective Socratic tutoring. In this architecture, sycophancy is mitigated by separating the system's components:

* **Sycophancy Gate**: The Conversational Tutor is strictly prohibited from using non-constructive praise, validation phrases, or agreeable responses .
* **Semantic Verification Loop**: Every historical or technical claim made by the user is evaluated against the ground-truth metadata in Tier 2 . If a claim cannot be verified, the system triggers a gentle clarification prompt rather than confirming the observation (e.g., "The sequence record does not show a tracking shot at this timestamp; re-examine the transition between these two frames.") .

### Turn Evaluation via Orthogonal Pairwise Judging To maintain high pedagogical standards without introducing self-grading bias, the tutor does not evaluate its own responses. Instead, the system uses an independent LLM judge that has no role in authoring the dialogue. This external judge evaluates pairs of potential tutor turns (e.g., comparing a candidate Socratic response with a baseline response) based on how well they adhere to scaffolding rules, maintain appropriate tone, and avoid sycophantic praise .

---

## Continuous Improvement Pipeline

To ensure the tutoring agent adapts and improves over the course of the 150-film curriculum, the system operates within a continuous, automated improvement pipeline. This pipeline uses real session transcripts to refine prompts, update domain models, and maintain strict pedagogical standards.

```
                  [ Real-Time Session Transcripts ]
                                  |
                                  v
                  [ Automated Regex & NLP Parser ]
                                  |
                                  v
+-------------------------------------------------------------------+
| GOLD-STANDARD REGRESSION EVALUATION SUITE                         |
| - 100+ Multi-Turn Dialogue Scenarios                              |
| - Canonical Correct Responses & Visual Evidence Pairs             |
| - Accessible Audio-First Phonetic/Formatting Guidelines           |
+-------------------------------------------------------------------+
                                  |
                        [Prompt Optimization]
                                  v
+-------------------------------------------------------------------+
| AUTOMATED REGRESSION GATE (JUDGE LLM)                            |
| - Evaluates proposed agent prompts against gold-standard cases     |
| - Rejects prompts that introduce sycophancy or reduce scaffolding |
| - Verifies phonetic flow and structure for text-to-speech rendering|
+-------------------------------------------------------------------+
                                  |
                       [Passes Validation Gate]
                                  v
                  [ Deployed Production System ]
```

### The Evaluation Dataset and Regression Testing Gates The pipeline is anchored by a curated evaluation suite containing over 100 multi-turn dialogue scenarios compiled from the user's actual interactions. Each scenario includes:
* The active conversation history.
* The user's sealed recall profile.
* The corresponding ground-truth metadata from Tier 2.
* A set of reference tutor responses representing ideal scaffolding moves.

Before any updates are made to the agent's prompts or underlying models, the proposed changes must pass through a regression testing gate. The evaluation suite runs the new configuration against all archived scenarios. The independent judge LLM evaluates the newly generated tutor turns against the reference responses, scoring them on:
* **Scaffolding Retention**: Ensuring the agent does not provide answers prematurely .
* **Phonetic Clarity**: Verifying that the language remains clean and readable when processed by text-to-speech software, avoiding complex syntactic structures that are difficult to parse aurally.
* **Non-Sycophancy**: Confirming the agent maintains an objective, neutral, and constructive tone .

If the updated configuration fails to meet or exceed the performance of the existing model, the update is rejected, and the system reverts to the previous configuration.

### The Kaizen Optimization Loop The continuous improvement loop operates on a recurring cycle:
1. **Transcribing**: Active session audio is transcribed and checked for phonetic clarity and formatting inconsistencies that could affect text-to-speech rendering.
2. **Parsing**: Automated parsers extract key dialogue metrics, including user-to-agent talk ratios, scaffolding transition rates, and calibration curves .
3. **Evaluating**: The independent judge evaluates the tutor's responses against the golden evaluation set to identify areas of deviation or degradation.
4. **Updating**: System prompts, dialogue state weights, and vocabulary trees are adjusted based on the evaluation data.
5. **Testing**: The updated configuration is run through the regression gate to ensure it meets performance standards before being deployed to production.

---

## Quick-Reference System Matrix

This matrix maps the tutor's conversational moves to their underlying cognitive mechanisms and process measures.

| Tutor Move | Cognitive Mechanism | Primary Source | Operational Process Metric
| Target Threshold |
| :--- | :--- | :--- | :--- | :--- |
| **Silent Reactivity** | Generation Effect  | Sealed Recall Protocol | **Tutor Lead Counter**: Total agent-initiated dialogue turns per session. | $0.0$ turns initiated by the agent. |
| **Conversational Pump** | Retrieval Practice  | EMT Dialogue Model  | **User Elaboration Rate**: Average word count of the user's response to the pump. | $\ge 45$ words generated per response. |
| **Cinematographic Hint** | Contingent Scaffolding  | Zone of Proximal Development  | **Target Attention Alignment**: Whether the user's next turn addresses the target visual feature. | $\ge 80\%$ alignment rate. |
| **Flavor-Wheel Prompt** | Active Vocabulary Integration | Sensory Taxonomy  | **Taxonomic Accuracy**: Use of correct terminology from the Flavor-Wheel Tree. | User applies the correct visual term. |
| **Direct Assertion** | Information Consolidation  | EMT Dialogue Model  | **Scaffolding Exhaustion Rate**: Frequency of assertions required per session. | $\le 10\%$ of total scaffolding pathways. |
| **Predict-Before-Reveal** | Hypothesizing  | Error-Driven Learning  | **Brier Score Calibration**: Accuracy of user-assigned probabilities for craft decisions . | $BS \le 0.15$ over a 10-scene window . |
| **Interleaved Comparison** | Contextualization  | Cognitive Interleaving  | **Pairwise Integration Index**: Frequency of cross-film comparisons initiated by the user. | $\ge 1.0$ comparative heat per session. |

---

## Verification Protocols ($n=1$ Experiments)

### Experiment 1: Evaluating the Hypercorrection Effect under Audio-Only Conditions This experiment evaluates whether correcting high-confidence visual-sensory errors under audio-only conditions leads to better long-term visual discrimination than correcting low-confidence errors.

* **Experimental Protocol**:
  1. The tutor selects 20 distinct shots from the 150-film canon displaying varying degrees of focal-length-induced spatial compression or distortion.
  2. For each shot, the user must identify the focal length range used (e.g., wide, normal, telephoto) and state their confidence in their judgment as a subjective probability ($P \in [0.10, 1.00]$).
  3. The tutor registers these predictions and categorizes errors into two groups: High-Confidence Errors ($P \ge 0.85$) and Low-Confidence Errors ($P \le 0.60$) .
  4. For both groups, the tutor applies a Socratic scaffolding sequence to guide the user to the correct lens classification .
  5. Two weeks later, the user is presented with a new, interleaved set of shots displaying similar spatial properties. The user's classification accuracy is then re-evaluated.
* **Evaluation Metrics**: The primary metric is the difference in error reduction rates between high-confidence and low-confidence scenarios:

$$\Delta E = \text{Accuracy}_{\text{High-Confidence Retest}} - \text{Accuracy}_{\text{Low-Confidence Retest}}$$

* **Evidence Classification**: **Robust** . The hypercorrection effect is well-documented in cognitive psychology, showing that correcting confident errors consistently leads to stronger updates to a learner's conceptual schema .

### Experiment 2: Comparative Heats versus Rubric-Based Aesthetic Evaluation This experiment compares the learning efficiency of pairwise aesthetic comparison ("comparative heats") against traditional multi-axis rubrics for an audio-first learner with text-processing accommodations.

* **Experimental Protocol**:
  1. The 150-film curriculum is divided into two distinct, balanced study blocks of 10 films each.
  2. **Block A (Traditional Rubric)**: The user evaluates key scenes using a multi-axis scoring model (e.g., rating performance, editing, lighting, and composition on separate 10-point scales). The tutor reviews these scores and discusses them using traditional rubric parameters.
  3. **Block B (Comparative Heats)**: The user does not assign numerical scores. Instead, the tutor presents a series of comparative pairings, matching scenes from the current film with scenes from previously viewed films in the canon (e.g., "Compare the use of deep focus in this shot with its use in the preceding film"). The user analyzes these scenes by contrasting their visual qualities, navigating the comparison using the branches of the Flavor-Wheel Tree .
  4. After completing both blocks, the user is tested on their ability to classify and analyze visual styles in 10 novel scenes.
* **Evaluation Metrics**:
  1. **User Analytical Fluency**: Measured by the user-to-agent talk ratio and the depth of descriptive vocabulary used in subsequent sessions .
  2. **Cognitive Load Index**: Self-reported cognitive fatigue scores, assessed via verbal feedback after each session, evaluating the impact of the visual-spatial interface on the learning process.
  3. **Visual Discrimination Accuracy**: Performance on the style classification test.
* **Evidence Classification**: **Emerging** . While comparative judgment is an established method in psychophysics, its application as a replacement for structured rubrics within conversational intelligent tutoring systems remains an emerging area of research that requires further validation in aesthetic domains.

---

1. The Role of the Lecturer as Tutor: Doing What Effective Tutors Do in a Large Lecture Class - PMC, (https://pmc.ncbi.nlm.nih.gov/articles/PMC3292071/)
2. AutoTutor and Affective AutoTutor: Learning by Talking with Cognitively and Emotionally Intelligent Computers that Talk Back - ida.liu.se, (https://www.ida.liu.se/divisions/hcs/seminars/cogsciseminars/Papers/dmello-TiiS12.pdf)
3. Operation ARIES!: Methods, Mystery, and Mixed Models: Discourse Features Predict Affect in a Serious Game - Journal of Educational Data Mining, (https://jedm.educationaldatamining.org/index.php/JEDM/article/download/33/23)
4. autotutor - CDN, (https://cpb-us-w2.wpmucdn.com/blogs.memphis.edu/dist/d/2954/files/2019/10/unreasonable-autotutor-authorversion-final.pdf)
5. Design and Development of an Adaptive Hypermedia-Based Course for Counterinsurgency Training in GIFT: Opportunities and Lessons, (https://gifttutoring.org/attachments/download/2689/06_GIFTSym6_Instr%20Mgt_paper_24.pdf)
6. The Learning Pyramid Explained - Learning Hub, (https://learning.iorad.com/thought-leadership/the-learning-pyramid-explained)
7. Intelligent tutoring systems (its) for online learning, (https://quality.mit.edu/files/2012/01/Quality-Symposium-Kurt-VanLehn.pdf)
8. Investigating how student's cognitive behavior in MOOC discussion forums affect learning gains - Educational Data Mining, (https://www.educationaldatamining.org/EDM2015/uploads/papers/paper_89.pdf)
9. Note-taking and science inquiry in an open-ended learning environment - PMC, (https://pmc.ncbi.nlm.nih.gov/articles/PMC6291433/)
10. PBL and Beyond: Trends in Collaborative Learning | Request PDF - ResearchGate, (https://www.researchgate.net/publication/258641079_PBL_and_Beyond_Trends_in_Collaborative_Learning)
11. Investigating the Role of Student Motivation in Computer Science Education through One-on-One Tutoring, (https://cise.ufl.edu/research/learndialogue/pdf/LearnDialogue-Boyer-ComputerScienceEducation-2009.pdf)
12. Formalisation and implementation of motivational tactics in tutoring systems - University of Sussex, (https://www.sussex.ac.uk/informatics/cogslib/reports/csrp/csrp345.pdf)
13. Modelling human teaching tactics and strategies for tutoring systems, (https://figshare.com/ndownloader/files/41099993/1)
14. Writing Studio Motivational Strategies Intrinsic Motivation = Interest + Personal Control Motivation influences and is influence, (https://www.vanderbilt.edu/writing/wp-content/uploads/sites/135/2016/10/WS-handout-on-motivation.pdf)
15. Intrinsic Motivation and instruction: conflicting Views on the Role of Motivational Processes in Computer-Based Education | Semantic Scholar, (https://www.semanticscholar.org/paper/Intrinsic-Motivation-and-instruction%3A-conflicting-Lepper-Chabay/500a6442019aa0a76db5191b78405661cbd5c6eb)
16. Intrinsic Motivation and the Process of Learning: Beneficial Effects of Contextualization, Personalization, and Choice - ResearchGate, (https://www.researchgate.net/profile/Mark-Lepper-2/publication/232529695_Intrinsic_Motivation_and_the_Process_of_Learning_Beneficial_Effects_of_Contextualization_Personalization_and_Choice/links/56107d6608ae0fc513f13bd2/Intrinsic-Motivation-and-the-Process-of-Learning-Beneficial-Effects-of-Contextualization-Personalization-and-Choice.pdf)
17. The Role of Positive Feedback in Intelligent Tutoring Systems - ACL Anthology, (https://aclanthology.org/P08-3006.pdf)
18. Designed-in and contingent scaffolding in the Teaching Practice Groups model - UPI, (https://ejournal.upi.edu/index.php/IJAL/article/download/16141/9683)
19. Build It and They Will Learn: Scaffolding Success | The International Educator (TIE Online), (https://www.tieonline.com/article/7911/build-it-and-they-will-learn-scaffolding-success)
20. Instructional scaffolding - Wikipedia, (https://en.wikipedia.org/wiki/Instructional_scaffolding)
21. (PDF) AutoTutor and Family: A Review of 17 Years of Natural Language Tutoring, (https://www.researchgate.net/publication/266398403_AutoTutor_and_Family_A_Review_of_17_Years_of_Natural_Language_Tutoring)
22. (PDF) AutoTutor: An Intelligent Tutor and Conversational Tutoring Scaffold - ResearchGate, (https://www.researchgate.net/publication/254375695_AutoTutor_An_Intelligent_Tutor_and_Conversational_Tutoring_Scaffold)
23. Student Prior Knowledge and Learning in an Intelligent Tutoring System: Comparing the Effectiveness of Vicarious and Interactive Dialogues - University of Memphis Digital Commons, (https://digitalcommons.memphis.edu/cgi/viewcontent.cgi?article=4384&context=etd)
24. CHAPTER 5 –A Review of Student Models Used in Intelligent Tutoring Systems - CDN, (https://bpb-us-w2.wpmucdn.com/blogs.memphis.edu/dist/d/2954/files/2019/10/pavlik_studentmodels_2013.pdf)
25. The Pretesting Effect: Why Testing Before Teaching Works - Structural Learning, (https://www.structural-learning.com/post/pretesting-effect-testing-before-teaching)
26. From Obstacle to Catalyst: A Narrative Review of Learning from Errors in Science Education, (https://www.mdpi.com/2673-8392/6/9/192)
27. UNIVERSIDADE DE LISBOA FACULDADE DE PSICOLOGIA THE, (https://repositorio.ulisboa.pt/bitstream/10451/58445/1/ulfpie058194_tm.pdf)
28. Learning from Mistakes: Why Errors Are Essential for Growth | Active, (https://activerecalling.com/blog/mistake-driven-learning)
29. Design Recommendations for Intelligent Tutoring Systems - GIFT, (https://gifttutoring.org/attachments/download/645/Design%20Recommendations%20for%20ITS_Volume%201%20-%20Learner%20Modeling%20Book_errata%20addressed_web%20version.pdf)
30. Design Recommendations for Intelligent Tutoring Systems - GIFT, (https://gifttutoring.org/attachments/download/1071/Design_Recommendations_for_Intelligent_Tutoring_Systems_Volume%203%20Final.pdf)
31. Coffee Flavor Wheel: History, Science & How to Use It, (https://dabov.us/blog/the-evolution-of-the-coffee-flavor-wheel-past-and-present)
32. Modified Brier score for evaluating prediction accuracy for binary outcomes - PMC, (https://pmc.ncbi.nlm.nih.gov/articles/PMC9691523/)
33. brier-score - renayo.shop - Obsidian Publish, (https://publish.obsidian.md/renayo/Belief+Tracker/Documentation/calibration/brier-score)
34. Brier Score: Measure Model Calibration & Accuracy | Ultralytics, (https://www.ultralytics.com/glossary/brier-score)
35. When High Accuracy Hides Poor Calibration: Rethinking Confidence Evaluation in Transformer-Based Text Classification with Balanced Brier Score - ACL Anthology, (https://aclanthology.org/2026.acl-long.2128/)
36. ConfidenceBench: Evaluating Confidence Calibration in Large Language Models - arXiv, (https://arxiv.org/html/2607.20526v1)
37. How Accurate Are Our Predictions? - Coefficient Giving, (https://coefficientgiving.org/research/how-accurate-are-our-predictions/)
38. Model Calibration, Explained: A Visual Guide with Code Examples for Beginners, (https://towardsdatascience.com/model-calibration-explained-a-visual-guide-with-code-examples-for-beginners-55f368bafe72/)
