---
title: "Systems-Architected Connoisseurship: Integrating Sensory, Perceptual, and Cognitive Frameworks into an Automated Film Tutor Agent"
type: deep-research
extraction: flat-research-report
sources_found: 72
created: 2026-09-11
tags: []
origin_repo: praxis-halo
origin_path: raw/151-how-taste-is-taught.md
origin_sha256: 47d5f5232c8f4e518a0f819e69f7aa1f415e808baaa5f2e5cca224dc8fbebdba
scrub_rules: handoff/scrub-rules/151.rules
scrub_rules_sha256: 062423148af76494d30a3633b63daae3a162c0bb93d1145a6e1a6ef778cb3792
scrubbed_on: 2026-09-13
handoff_bundle: 2026-09-13-movie-brain-cartridge
derivative: scrubbed
origin_id: 151
---

# Systems-Architected Connoisseurship: Integrating Sensory, Perceptual, and Cognitive Frameworks into an Automated Film Tutor Agent

Developing an automated tutoring agent to cultivate aesthetic taste across a 150-film canon requires a systematic synthesis of established sensory, artistic, and cognitive methodologies. A learner with an analytical background, a trained visual eye from an adjacent craft, and formal sensory-judging experience provides an ideal epistemic foundation for this architecture. Rather than inventing a novel training framework, this report deconstructs and weaponizes existing pedagogical models that teach taste for a living.

This architecture operates on four core premises: taste is a stable, discriminative disposition that can be logically defended; cognitive recall must be structurally sealed and isolated before critical evaluation begins; the tutoring agent must never rank or evaluate on behalf of the user; and learning is driven by the cognitive friction of direct contrast and comparative pairing rather than abstract rubrics.

---

## The Sommelier and Spirits-Judge Pipeline: Deconstructing Sensory Calibration and Panel Stochasticity

The systematic evaluation of complex chemical compounds in sommellerie and spirits judging represents the most highly formalized industrial model of taste instruction . The Wine & Spirit Education Trust (WSET) utilizes the Systematic Approach to Tasting (SAT) to decompose sensory experience into rigid, sequential parameters: appearance, nose, and palate, culminating in a logical synthesis of quality and readiness . Similarly, the Court of Master Sommeliers (CMS) deploys its Deductive Tasting Grid to guide tasters through visual, olfactory, and structural vectors to systematically eliminate incorrect options and arrive at a defensible conclusion regarding variety, origin, climate, and vintage .

```
                     [PHYSICAL STIMULUS: LIQUID / MOVING IMAGE]
                                        │
                                        ▼
                         [PHASE 1: THE LOOK-LOCK FILTER]
                      - Complete isolation of physical facts
                      - Forbidden evaluative terminology
                      - Objective feature gridding (Luminance, Vectors)
                                        │
                                        ▼
                         [PHASE 2: THE CONTRASTING CASE]
                      - Paired presentations (A vs. B)
                      - Single-variable isolation (LUT, Lens, Edit)
                      - High-heat comparison before conceptualization
                                        │
                                        ▼
                       [PHASE 3: SPEED REACTION ATTRIBUTION]
                      - Interleaved classification (French New Wave)
                      - Spatiotemporal chunking & PLM automated loop
                      - Response-time category sequencing algorithms
                                        │
                                        ▼
                         [PHASE 4: COMPARATIVE SUMMATION]
                      - Adaptive Comparative Judgment (ACJ) duels
                      - Bradley-Terry latent scaling calculations
                      - Verification of Judgement Consistency Coefficient
```

This training is designed to isolate objective physical sensations from cognitive preconceptions . The appearance phase establishes a baseline, using color hue, intensity, and viscosity to generate early hypotheses regarding aging, grape variety, and alcohol or sugar concentrations . The olfactory phase segments aromas into primary (varietal fruits and herbs), secondary (vinification-derived artifacts such as oak, MLF, or yeast autolysis), and tertiary (oxidative or reductive aging) categories . The palate phase isolates structural dimensions: acidity (perceived via salivary stimulation), tannins (measured by tactile astringency on the gums), alcohol (perceived as thermal sensation), and body .

However, longitudinal studies of expert performance reveal significant reliability limitations in these panels. Robert Hodgson’s landmark statistical evaluations of wine judges at the California State Fair Commercial Wine Competition demonstrated that expert evaluations are heavily influenced by experimental error and cognitive bias . Over several years of presenting panels with blind triplicate samples poured from the exact same bottle, Hodgson found that only $10\%$ of elite judges consistently scored the replicates within a narrow range of $\pm 2$ points or one medal class . Another $10\%$ exhibited extreme inconsistency, assigning the identical wine scores that spanned from Bronze to Gold (a disparity of up to 14 to 16 points) . Furthermore, the consistency of individual judges did not persist from year to year; a judge who demonstrated high reliability in Year 1 frequently failed to replicate that performance in Year 2 . This instability is compounded across events: $99\%$ of wines that received gold medals at one U.S. competition received no awards at other major competitions .

```
                [ HODGSON COMPETITION DATA DISTRIBUTION ]

               100% ┼────────────────────────────────────
                    │
                80% ┼────────────────────────────────────
                    │
                60% ┼────────────────────────────────────
                    │
                40% ┼────────────────────────────────────
                    │
                20% ┼───[Consistent]───[Inconsistent]────
                    │       10%             10%
                 0% ┴────────────────────────────────────
                    (99% of gold medals fail to replicate across competitions)
```

The American Association of Wine Economists (AAWE) expanded on this by evaluating ranks assigned to replicates across an ordered set of ten award-level ranks (No Award, Bronze-, Bronze, Bronze+, Silver-, Silver, Silver+, Gold-, Gold, Gold+) . Their probability distributions confirmed that while perfect consistency is rare, judges do assign closer ratings to replicates than due to chance alone—approximately one-third of judges scored within 1 rank, and two-thirds scored within 2 ranks of perfect consistency .

The distribution of gold medals across large datasets closely tracks a classic binomial distribution, where the probability of winning a gold medal, $p$, is approximately $0.10$ by chance alone, regardless of the intrinsic quality of the wine .

To mitigate these errors, the International Organisation of Vine and Wine (OIV) implements statistical adjustments for judge bias and restricts judges to evaluating no more than 50 wines per day in quiet, isolated settings . These steps prevent visual parameters, particularly chromatic characteristics, from overriding olfactory and gustatory pathways, a bias demonstrated in Bordeaux studies where tasters perceived red wine descriptors in white wines colored with tasteless red dyes .

For the tutor agent, this reveals a crucial design principle: visual cues set powerful cognitive expectations that override other sensory and interpretive channels . The tutor must enforce strict boundaries between descriptive, formal, and evaluative phases to prevent early cognitive closure and stabilize taste evaluation.

---

## Pedagogies of Vision: Art-School Critique, Connoisseurship, and Collaborative Friction

Aesthetic education in the visual and performing arts relies on structured observational protocols to prevent immediate, unreflective judgment and cultivate deep connoisseurship. Edmund Feldman’s four-stage method of art criticism represents a classic model designed to scaffold visual analysis in classroom and professional settings . The method enforces a strict cognitive firewall between observation and evaluation through four linear steps:

1.  **Description:** The viewer inventories the objective, factual properties of the artwork (such as medium, scale, colors, and subject matter) without employing evaluative or emotive language . Speculative words like "beautiful," "chaotic," or "masterful" are forbidden to prevent early cognitive closure .
2.  **Formal Analysis:** The viewer examines the structural, geometric, and technical organization of the piece . This involves identifying how the elements of art (lines, shapes, values, textures) interact via the principles of design (balance, focal points, scale, directional movement) to guide the viewer's eye across the composition .
3.  **Interpretation:** The viewer reconstructs the expressive qualities, metaphoric content, and conceptual intent of the artwork . This phase translates formal organization into meaning, postulating what ideas or emotional states the artist is communicating .
4.  **Judgment:** Only after completing the prior steps does the viewer make an evaluative claim . This judgment is not based on personal preference, but rather on comparing the artwork's execution and originality against established historical, cultural, or stylistic benchmarks .

```
                     [FELDMAN'S ART CRITICISM TIMELINE]

       ┌───────────────┬────────────────┬─────────────────┬─────────────┐
       │  Description  │ Formal Analysis│  Interpretation │  Judgment   │
       │  (Objective)  │  (Structural)  │   (Expressive)  │ (Evaluative)│
       └───────────────┴────────────────┴─────────────────┴─────────────┘
       0m             5m               15m               25m           30m
                     ▲                                    ▲
                     │                                    │
               [COGNITIVE FIREWALL]                 [EVALUATIVE REVEAL]
```

In the field of historical connoisseurship, the Berenson and Morelli methods represent highly specialized techniques for artistic attribution based on forensic visual evidence. Giovanni Morelli asserted that copyists and students can easily duplicate the prominent, expressive elements of a master's style (such as the central composition or dramatic lighting). To identify authentic authorship, Morelli directed attention to minor, highly habituated, and unconsciously executed details that escape the copyist's notice—such as the rendering of earlobes, fingernails, or drapery folds. Bernard Berenson expanded this approach into a systematic discipline of visual connoisseurship, prioritizing tactile values, movement, and forensic anatomical details over broad stylistic declarations.

In the performing arts, the conservatory masterclass provides a model of pedagogic training driven by "constructive friction" . A student performs a piece before a master instructor and an audience of peers, followed by an immediate, highly granular critique . The masterclass targets "double-loop learning"—distinguished by Chris Argyris and Donald Schön from "single-loop learning" . While single-loop learning functions like a thermostat, correcting deviations from a fixed set-point without questioning the metric itself, double-loop learning interrogates the underlying assumptions, values, and interpretive frameworks that govern the performance . In a masterclass, the instructor does not simply correct a wrong note; they challenge the student's entire conception of phrasing, historical ornamentation, and emotional architecture .

---

## Neoformalist Film Pedagogy: Deconstructing Style as Problem-Solving

Formal film pedagogy translates these visual and analytical disciplines to the moving image. David Bordwell and Kristin Thompson’s neoformalist framework, detailed in their seminal text *Film Art*, approaches cinema as a dynamic aesthetic system structured by formal techniques . Neoformalism, drawing on Russian formalist literary theory, operates on the premise that art performs "defamiliarization"—making the familiar and formulaic strange to encourage active, conscious perception .

The neoformalist model rejects "Grand Theories" (such as psychoanalytic or poststructuralist paradigms) that use films to confirm pre-existing ideological constructs . Instead, it advocates for mid-level research and "historical poetics," which analyze film style as a series of creative, causal responses to specific artistic, economic, and technological problems . The model decomposes film style into four primary formal systems :

*   **Mise-en-scène:** The staging of action within the frame, including setting, lighting, costume, and figure movement .
*   **Cinematography:** The framing, camera movement, lens selection, and chemical/digital properties of the shot .
*   **Editing:** The spatial, temporal, and rhythmic relations established between shots .
*   **Sound:** The acoustic properties (pitch, timber, volume), spatial sources (diegetic vs. nondiegetic), and temporal alignment of dialogue, effects, and music.

To operationalize this level of formal scrutiny, pedagogues utilize structured viewing exercises:

*   **Shot-by-Shot Analysis:** This method requires the absolute decomposition of a scene, mapping every cut, camera movement, framing change, and sound transition to analyze how these stylistic choices build the film's narrative logic.
*   **Ebert’s Cinema Interruptus:** Pioneered by film critic Roger Ebert, this pedagogical format involves a collective, democratic reading of a film . The facilitator projects a film, and any participant can call out "Stop!" to pause the frame. The group then analyzes the static image, unpacking its composition, lighting, lens characteristics, and narrative markers. This freeze-frame methodology mimics the slow, deliberate inspection of static fine art, counteracting the rapid temporal flow of cinema that often obscures formal mechanics.

---

## The Cognitive Science of Perceptual Learning: Interleaving, Contrast, and Sensory Optimization

To automate the acquisition of cinematic taste, a tutoring agent must align its pedagogical moves with the cognitive mechanisms of perceptual learning and category induction. Perceptual learning is defined as the lasting, structural modification of an organism's sensory systems in response to practice or exposure, leading to enhanced information extraction .

### Interleaved Learning and Discriminative Contrast Kornell and Bjork (2008) established that the sequencing of exemplars dictates the efficiency of inductive learning . When training individuals to recognize the distinct styles of different painters, presenting paintings in an interleaved sequence (Artist A, Artist B, Artist C, Artist A...) yields significantly higher classification accuracy on novel transfer paintings than a blocked sequence (Artist A, Artist A, Artist A, Artist B, Artist B...) .

This interleaving advantage is driven by "discriminative contrast" . By juxtaposing different categories in close temporal proximity, the visual system is forced to detect the subtle, diagnostic features that differentiate one class from another .

Conversely, blocked presentation emphasizes similarities within a single category, which fails to prepare the learner to distinguish that category from others . This mechanism is subject to a striking metacognitive illusion: approximately $80\%$ of participants falsely believe that blocked study is more effective, misinterpreting the ease of processing during blocked acquisition (which is temporary) as evidence of deeper learning .

```
                     [ NOVICE INTERLEAVED SCHEME ]
                       A1 ──► B1 ──► C1 ──► A2
                        ▲      ▲      ▲
                        └──────┴──────┴── [Discriminative Contrast]
                                           (Highlights Differences)

                      [ NOVICE BLOCKED SCHEME ]
                       A1 ──► A2 ──► A3 ──► A4
                        ▲      ▲      ▲
                        └──────┴──────┴── [Within-Class Association]
                                           (Obscures Diagnostic Boundaries)
```

In direct replications (online, $N=288$), interleaved presentation showed clear superiority over blocked presentation, yielding highly significant accuracy gains ($M = 0.79$, $95\%$ CI $[0.77, 0.81]$ for interleaved vs. $M = 0.73$, $95\%$ CI $[0.72, 0.75]$ for blocked; $t(275) = 7.19$, $p < 0.001$, $d_z = 0.43$) .

Furthermore, temporal spacing (inserting unrelated questions between exemplars) did not yield learning benefits and was shown to be harmful when it interrupted the active juxtaposition of interleaved categories, reinforcing that discriminative contrast—rather than simple decay or temporal spacing—is the primary driver of inductive acquisition .

### Contrasting Cases Daniel Schwartz and John Bransford’s (1998) "A Time for Telling" paradigm demonstrates that presenting novices with simplified, contrasting cases *before* delivering explicit instruction prepares them for deep comprehension . When students analyze paired, highly controlled contrasts (e.g., comparing two adjacent visual arrays that differ by only a single formal variable), they develop a highly differentiated, receptive knowledge structure. When the formal lecture or theory is subsequently introduced, the learner immediately connects the conceptual framework to the structural differences they have already observed .

In their experimental trials, college students asked to analyze and graph simplified datasets of memory experiments prior to a lecture demonstrated vastly superior conceptual transfer on subsequent tests compared to students who summarized a textbook chapter on the same experiments before hearing the lecture . Generating patterns from contrasting cases creates a cognitive "need to know," making subsequent direct instruction highly efficient .

### Perceptual Learning Modules (PLMs) Philip Kellman’s PLM technology leverages short, speeded, and varied classification trials accompanied by immediate feedback to bypass slow, deliberate reasoning and automate pattern recognition . Rather than relying on declarative or procedural instruction, PLMs target two key perceptual outcomes :

1.  **Discovery (Filtering and Selection):** The visual system learns to ignore irrelevant background noise and select only task-relevant, diagnostic structural relationships .
2.  **Fluency (Spatiotemporal Chunking):** Complex, disparate visual elements are integrated into singular, meaningful patterns, dramatically reducing cognitive load and visual search times .

Modern PLMs incorporate adaptive, response-time-based category sequencing algorithms, ensuring that items are spaced and re-presented based on both accuracy and latencies . This method accelerates the learner's speed from slow, conscious deduction to rapid, intuitive pattern recognition .

### Categorical Perception and the Expertise-Preference Shift Underlying this training is Robert Goldstone’s concept of categorical perception, wherein training alters basic sensory sensitivity. This process stretches the perceived distance between different categories (making them easier to distinguish) while compressing the perceived variation within a single category (stabilizing recognition).

As perceptual expertise develops, a fundamental shift in aesthetic preference occurs. Empirical aesthetics shows that novices prefer simple, symmetrical, highly prototypical stimuli because they are highly "fluent" and require minimal cognitive effort to process .

Conversely, experts prefer high-complexity, asymmetrical, and highly novel compositions . For an expert, aesthetic pleasure is generated by resolving visual tension, violating expectations, and engaging in high cognitive effort to decode complex, non-prototypical structures .

---

## Rubricless Taste Assessment: Adaptive Comparative Judgment and Calibrated Predictions

Assessing taste, connoisseurship, and aesthetic discernment has historically been constrained by the limitations of analytical rubrics. Rubrics frequently fragment holistic works of art into artificial, overlapping criteria, leading to poor inter-rater reliability and forcing judges to allocate arbitrary scores that fail to capture quality .

### Adaptive Comparative Judgment (ACJ) To bypass these limitations, Alastair Pollitt proposed Adaptive Comparative Judgment (ACJ), which is based on Thurstone’s Law of Comparative Judgment . ACJ operates on a simple cognitive premise: humans are highly unreliable when trying to assign an absolute numerical value to a complex, isolated object, but they are exceptionally consistent when directly comparing two objects and making a relative selection (e.g., deciding whether Screenplay A or Screenplay B exhibits superior pacing) .

In an ACJ assessment, an algorithm presents the evaluator with a series of pairs . The evaluator performs a rapid, holistic comparison, choosing the "better" of the two based on their internal, tacit standard of quality .

The algorithm estimates the latent quality of each item using the Bradley-Terry model :

$$\ln \left( \frac{P(i \succ j)}{1 - P(i \succ j)} \right) = \beta_i - \beta_j$$

where $\beta_i$ and $\beta_j$ are the estimated quality parameters of the respective items.

The adaptive mechanism dynamically pairs items with similar current quality estimates, which maximizes the statistical information generated by each comparison and rapidly drives down the standard error . ACJ achieves very high levels of reliability—often yielding a Judgment Consistency Coefficient (JCC) of $0.89$ to $0.95$ after 26 to 37 pairwise comparisons per item .

```
                     [ TRADITIONAL RUBRIC SCORING ]

       Criterion A: ──► [Score: 4] ──┐
       Criterion B: ──► [Score: 3] ──┼──► Absolute Sum: 10/15 (Low Reliability)
       Criterion C: ──► [Score: 3] ──┘

                     [ COMPARATIVE JUDGMENT (ACJ) ]

                     ┌───────────────────────────┐
                     │   Item X   vs.   Item Y   │
                     └───────────────────────────┘
                                   │
                                   ▼
                [Direct Holistic Decision: X is Better]
                                   │
                                   ▼
             [Bradley-Terry Parameter Scaling: JCC = 0.95]
```

Early critiques by Bramley (2015) and Wheadon (2015) suggested that the adaptive sequencing of ACJ could artificially inflate the JCC reliability statistic . However, subsequent large-scale simulations and mathematical corrections by Rangel Smith and Lynch (2018) verified that under realistic operational parameters, this upward bias is never greater than $0.004$, proving it to be statistically negligible and validating the tool for high-stakes, rubricless qualitative assessment .

Crucially, experimental data shows that while 10 to 14 comparisons per item are required to reach a baseline reliability of $0.70$, 26 to 37 comparisons per item are necessary to secure a highly calibrated reliability of $0.90$ or above .

### Calibrating via Predict-Before-Reveal To calibrate the user's taste against an expert panel or historical critical consensus, the tutoring agent can implement a "predict-before-reveal" protocol. Instead of simply presenting an expert's critique or ranking, the agent requires the user to predict which of two film sequences an expert panel or historical consensus would rank higher along a specific formal dimension (e.g., depth-of-field complexity). This forces the user to actively model the expert's evaluation criteria.

The gap between the user’s prediction and the actual consensus provides a precise calibration metric:

$$\text{Calibration Error} = P(\text{User Selects } i \succ j \mid \text{Expert Consensus Selects } j \succ i)$$

This metric guides subsequent pedagogical interventions, targeting areas where the user's perceptual schema diverges from the target consensus.

---

## Systematic Mapping of Taste Practices to Automated Pedagogy

The following matrix maps the professional practices analyzed above to their underlying cognitive mechanisms, automated tutoring translations, evaluation metrics, and cinematic boundaries.

| Practice Domain | Underlying Mechanism | Tutor Agent Move | Quantitative Metric | Cinematic Transfer (What Transfers) | Cinematic Non-Transfer (What Does Not) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Sommellerie & Spirits Judging (WSET SAT & CMS Grid)**  | Deductive category partitioning; logical sensory isolation; physical bias reduction . | **Deductive Visual Partitioning:** Lock interactive frames; force objective visual attribute inventory (aspect ratio, focus plane, luminance) before unlocking text or metadata . | **Sighting Categorical Accuracy:** Error rate against master computer-vision parameters; response latencies under locked conditions. | Technical, static composition features; lens aberrations; depth of field; lighting contrast ratios; color saturation metrics . | Temporal narrative progression; emotional performances; complex screenwriting subtext; dialogic irony . |
| **Art-School Critique (Feldman’s Method)**  | Structural separation of descriptive, formal, interpretive, and evaluative cognitive states . | **"Look-Lock" Sequence:** Programmatically restrict entry of interpretive and evaluative inputs until descriptive checklist is executed . | **Description-to-Evaluation Latency:** Milliseconds elapsed under strict objective description before evaluative terms are unlocked. | Frame spatial architecture; geometry of actor blocking; color interactions; directional visual vectors . | Temporal sound design; cross-cut pacing; kinetic frame-rate manipulations . |
| **Aesthetic Connoisseurship (Berenson & Morelli)** | Forensic micro-attribution; focus on unconscious, non-mimetic technical details. | **Morellian Cinematic Profiling:** Require high-frequency classification of minor technical details (e.g., lens flare rendering, transition style, focal breathing). | **Attribution Accuracy ($d'$ Sensitivity):** Ability to correctly isolate director stylistic signatures from generic studio templates. | Director-specific technical quirks; camera-rig signatures; idiosyncratic lighting setups . | High-concept genre tropes; macro narrative structures; shared industrial studio templates . |
| **Conservatory Masterclass (Schön & Argyris)**  | Constructive friction; double-loop learning; interrogation of underlying values . | **Constructive Friction Coach:** Prompt comparative analysis challenging user's taste criteria against critical consensus. | **Double-Loop Iteration Metric:** Frequency of user altering their baseline aesthetic criteria when confronted with contrast. | Structural interpretative framing; cognitive approach to composition and narrative logic . | Isolated physical execution mechanics; physiological sensory limits. |
| **Film Pedagogy (Ebert’s Cinema Interruptus)**  | Manual temporal deceleration; active spatial frame segmentation. | **The Interruptus Pause-Engine:** Intermittent, randomized screen freezes forcing user to map spatial graphic composition vectors. | **Vector Alignment Score:** Pixel-level distance accuracy when tracing visual lines of action and eye-lines. | Visual balance; composition; staging; lighting vectors; color blocking . | Rhythmic editing intervals; auditory panning; dialogue delivery; acoustic atmospheric spacing . |
| **Cognitive Science (Interleaved Painters)**  | Discriminative contrast; extraction of diagnostic category boundaries . | **Interleaved Director Flights:** Display 5-second clips of similar genres (e.g., Neo-noir) by alternating directors (e.g., Melville, Welles, Huston) . | **Induction Accuracy Gain:** Differential score improvement on novel film attribution under interleaved vs. blocked training . | Director stylistic signatures across varied budgets and genres; spatial-continuity variations . | Historical context shifts; technical jumps in equipment; performance style of actors . |
| **Cognitive Science (Contrasting Cases)**  | Differentiated visual schema construction; preparation for future learning . | **Single-Variable Isolated Pairs:** Side-by-side scenes identical in all variables except one (e.g., identical shot filmed at 24mm vs. 85mm) . | **Structural Variable Sensitivity:** Accuracy in identifying the manipulated technical variable and its emotional impact. | Deep, structural comprehension of technical tools and their direct rhetorical/emotional effects . | Complex, real-world scenes where multiple technical variables shift simultaneously, obscuring individual effects . |
| **Cognitive Science (Perceptual Learning Modules)**  | Sub-second visual pattern extraction; spatiotemporal chunking; automated fluency . | **Cinematic PLM Classification Engine:** Forced-choice classification of sub-second editing styles and camera movements . | **Fluency Index ($FI$):** Formulated as $FI = \frac{ACC}{\ln(RT)}$ where $ACC$ is accuracy and $RT$ is reaction time in ms . | Sub-second pattern extraction; editing transition types; camera tracking speeds; lighting layout recognition . | Long-form story arcs; complex character development; intellectual symbolism; structural editing motifs . |
| **Cognitive Science (Categorical Perception & Shift)**  | Perceptual stretching of category boundaries; sensory-to-cognitive transformation. | **Visual Tension Scaling:** Push user toward high-complexity, asymmetric compositions to violate simple prototypical expectations . | **Preference Complexity Slope:** Statistical shift in user preference from high-symmetry to high-asymmetry over time . | Visual aesthetic discrimination; sensitivity to asymmetrical structural tension . | Literal non-visual storytelling elements; thematic narrative quality. |
| **Taste Assessment (Adaptive Comparative Judgment)**  | Holistic pairwise comparison; Thurstone's Law of Comparative Judgment; Bradley-Terry scaling . | **Dynamic Aesthetic Duel:** Present pairs of film clips from the 150-film canon, using a Swiss Tournament to pair similar-quality clips . | **Judgment Consistency Coefficient (JCC):** Internal statistical reliability of relative preferences . | Nuanced, relative ranking of the user's 150-film canon based on personal aesthetic taste . | Absolute, static scoring; universal cross-user benchmarks (rankings remain fundamentally relative to the input set) . |

---

## Technical Architecture Blueprint: The Onboarding Session (60-Minute Runtime)

This blueprint details a 60-minute, automated onboarding session engineered to calibrate the user's taste and baseline visual perception without rubrics, leveraging their analytical, visual, and sensory-evaluation background.

```
       ┌─────────────────────────────────────────────────────────────────┐
       │             STAGE 1: SYSTEMATIC CINEMATIC TASTING               │
       │                   Timeframe: 00:00 - 00:10                      │
       ├─────────────────────────────────────────────────────────────────┤
       │             STAGE 2: CONTRASTING CASES & ISOLATION              │
       │                   Timeframe: 00:10 - 00:22                      │
       ├─────────────────────────────────────────────────────────────────┤
       │             STAGE 3: TIMED INTERLEAVED PLM LOOP                 │
       │                   Timeframe: 00:22 - 00:35                      │
       ├─────────────────────────────────────────────────────────────────┤
       │             STAGE 4: MORELLIAN CINEMA INTERRUPTUS               │
       │                   Timeframe: 00:35 - 00:48                      │
       ├─────────────────────────────────────────────────────────────────┤
       │             STAGE 5: RUBRICLESS ACJ INITIALIZATION              │
       │                   Timeframe: 00:48 - 01:00                      │
       └─────────────────────────────────────────────────────────────────┘
```

### Stage 1: Systematic Cinematic Tasting & Sighting (00:00 - 00:10)
*   **Target Core Practice:** WSET SAT Appearance Framework  combined with Feldman’s Descriptive Stage .
*   **Cognitive Mechanism:** Preventing cognitive closure; sealing descriptive recall before allowing evaluative judgment .
*   **Automated Agent Choreography:**
    1.  The agent projects a static 4K frame from Yasujiro Ozu’s *Tokyo Story* (1953) on a color-calibrated screen, locking out all film titles, year labels, director metadata, and textual inputs.
    2.  The interface prompts the user to complete a "Cinematic Sight Grid" to document the objective, physical properties of the frame .
    3.  The user must identify the aspect ratio (e.g., 1.37:1), map the luminance distribution by drawing bounding boxes around the brightest and darkest areas, and trace the focal plane boundary to separate sharp detail from out-of-focus background elements .
    4.  The system enforces a strict filter: any entry of evaluative terms (e.g., "gentle," "uncluttered," "sad") triggers an alert and locks input until an objective physical descriptor is used .
*   **Evaluation Target:** Sighting Categorical Precision, measured as the spatial overlap between the user's drawn bounding boxes and a computer-vision generated master analysis of the frame's optical parameters.

### Stage 2: Contrasting Cases & Feature Isolation (00:10 - 00:22)
*   **Target Core Practice:** Schwartz & Bransford’s "A Time for Telling" Paradigm .
*   **Cognitive Mechanism:** Building a highly differentiated visual schema before delivering conceptual instruction .
*   **Automated Agent Choreography:**
    1.  The agent presents a split-screen pairing of two identical close-up shots of an actor, showing a single controlled technical change. Shot A is filmed on a 24mm wide-angle lens at a close camera distance; Shot B is filmed on an 85mm telephoto lens at a further camera distance to maintain matching head size .
    2.  The interface instructs the user to analyze the contrast: "Measure the spatial distortion of the actor's nose and ears. Identify in which image the background details appear closer and more compressed behind the subject." No conceptual explanation of lenses or focal lengths is provided yet .
    3.  Once the user submits their observations, the agent delivers a highly focused, 90-second explanation of optical compression, focal lengths, and spatial representation .
*   **Evaluation Target:** Variable Isolation Accuracy, verifying the user's capacity to correctly trace optical differences before conceptual labels are applied.

### Stage 3: Timed Interleaved PLM Loop (00:22 - 00:35)
*   **Target Core Practice:** Kellman’s Perceptual Learning Modules (PLMs)  and Kornell & Bjork’s Interleaved Sequencing .
*   **Cognitive Mechanism:** Accelerating structure extraction and automating visual pattern recognition (fluency) via discriminative contrast .
*   **Automated Agent Choreography:**
    1.  The agent initiates a rapid-fire classification loop, presenting 3-second clips of action sequences .
    2.  The clips alternate in an interleaved sequence across directors who handle continuity editing differently (e.g., Jean-Luc Godard’s jump-cuts vs. Akira Kurosawa’s spatial match-cuts) .
    3.  The screen blackouts immediately after each clip. The user has a maximum of 1,200 milliseconds to classify the editing style as "Continuous Match" or "Discontinuous Jump" .
    4.  The system displays immediate visual feedback showing correctness and response time, adaptively scheduling subsequent trials based on performance .
*   **Evaluation Target:** Fluency Index ($FI$), calculated as accuracy over the natural log of reaction time ($FI = \frac{ACC}{\ln(RT)}$), tracking the progression from slow conscious deduction to rapid intuitive pattern recognition .

### Stage 4: Morellian Cinema Interruptus (00:35 - 00:48)
*   **Target Core Practice:** Ebert’s Cinema Interruptus  and Morellian Forensic Attribution.
*   **Cognitive Mechanism:** Decelerating time to extract diagnostic, non-mimetic technical details and style markers .
*   **Automated Agent Choreography:**
    1.  The agent projects a scene from Alfred Hitchcock’s *Vertigo* (1958) .
    2.  The program randomly pauses the film, freezing the frame and requiring the user to identify "Morellian technical details" (such as Hitchcock’s typical lighting ratios, camera tracking vectors, or background-foreground composition) .
    3.  The user is prompted to make a prediction before the next edit: "Will the next camera edit cut to a close-up tracking shot matching the vector, or will it transition to a static wide shot?"
    4.  The frame is unpaused, and the correct sequence is revealed.
*   **Evaluation Target:** Calibration on Predict-Before-Reveal, tracking the gap between the user's prediction and the actual technical choices of the director.

### Stage 5: Rubricless ACJ Initialization (00:48 - 01:00)
*   **Target Core Practice:** Pollitt’s Adaptive Comparative Judgment .
*   **Cognitive Mechanism:** Holistic relative comparison to bypass unreliable quantitative rubrics .
*   **Automated Agent Choreography:**
    1.  The agent presents a series of side-by-side video duels using clips from the user's 150-film canon .
    2.  For each pair, the user must make a relative judgment: "Which clip exhibits superior narrative momentum and editing continuity?" .
    3.  The user is instructed to perform rapid, holistic comparisons without analyzing individual rubrics or scoring guides .
    4.  The agent uses a Swiss Tournament pairing strategy for the first six rounds, then transitions to an adaptive algorithm to pair clips of similar estimated quality .
*   **Evaluation Target:** Latent quality scaling using the Bradley-Terry model, tracking the user’s baseline Judgment Consistency Coefficient (JCC) across 20 distinct duels .

---

## Single-Subject ($n=1$) Experimental Suite for Taste Refinement

These self-administered, single-subject ($n=1$) experiments allow the user to systematically track their development of film taste and perceptual sensitivity.

```
                  [ n=1 METHODOLOGY FLOW CHART ]

    [Experiment A] ──► Blocked vs. Interleaved Director Attribution
                       (Tests accuracy under discriminative contrast)
                             │
                             ▼
    [Experiment B] ──► Longitudinal Symmetry-to-Complexity Preference
                       (Tracks preference shifts using ACJ duels)
                             │
                             ▼
    [Experiment C] ──► Predict-Before-Reveal Calibration
                       (Quantifies alignment with critical consensus)
```

### Experiment A: Interleaved vs. Blocked Training on French New Wave Director Attribution
*   **Objective:** To determine if interleaved training yields superior visual attribution accuracy on novel films by Jean-Luc Godard, François Truffaut, and Claude Chabrol compared to blocked training .
*   **Independent Variable:** Sequencing of training clips: Blocked (Massed) vs. Interleaved (Spaced) .
*   **Dependent Variable:** Accuracy ($ACC$) on a final attribution test using novel, unseen 5-second clips, and subjective metacognitive confidence ratings (scale of 1 to 5) .
*   **Experimental Design (Within-Subject AB Reversal with Counterbalancing):**
    *   *Baseline Phase:* The user is exposed to 6 baseline clips from each director with no labels, recording baseline attribution accuracy.
    *   *Blocked Training (A):* The user studies 18 clips by Truffaut, presented in a continuous block of 6 clips per film . Under each clip, the director's name is clearly displayed for 5 seconds.
    *   *Interleaved Training (B):* The user studies 18 clips by Godard and Chabrol, presented in an interleaved sequence (Godard Clip 1, Chabrol Clip 1, Godard Clip 2, Chabrol Clip 2...) .
    *   *Interfering Distraction:* The user completes a 3-minute mathematical distraction task to clear working memory .
    *   *Testing Phase:* The user is presented with 12 novel, unlabelled clips (4 by Truffaut, 4 by Godard, 4 by Chabrol). The user must attribute each clip to its director. The user also records their subjective confidence on a scale of 1 to 5.
*   **Statistical Evaluation:** The program computes:

    $$\Delta ACC = ACC_{\text{Interleaved}} - ACC_{\text{Blocked}}$$

    The user’s calibration error is calculated as the gap between subjective confidence ratings and actual accuracy scores, demonstrating the presence of the metacognitive illusion .

### Experiment B: Longitudinal Tracking of the Symmetry-to-Complexity Preference Shift
*   **Objective:** To track whether the user's aesthetic preference shifts from simple, highly symmetrical, prototypical compositions to complex, asymmetrical compositions over 12 weeks of training .
*   **Independent Variable:** Accumulated hours of neoformalist film training (Weeks 1 through 12).
*   **Dependent Variable:** Aesthetic Selection Ratio ($\Psi_{Asymmetry}$), measured through holistic, rubricless ACJ duels comparing pairs of symmetrical and asymmetrical frames .
*   **Experimental Design (Longitudinal Interrupted Time-Series):**
    *   *Stimulus Pool:* 100 static frames are calibrated: 50 exhibiting strict bilateral symmetry (e.g., Ozu, Wes Anderson)  and 50 exhibiting complex, dynamic asymmetry (e.g., French New Wave, Orson Welles’ deep-focus dynamic angles) .
    *   *Baseline Phase (Week 1):* The user is presented with 30 randomized pairs (each pairing one symmetrical frame and one asymmetrical frame) and must select the frame they find more "aesthetically compelling" .
    *   *Training Intervention Phase (Weeks 2–11):* Continuous engagement with the film-tutor agent, emphasizing neoformalist visual analysis.
    *   *Post-Test Phase (Week 12):* The user repeats the identical 30-pair ACJ duel under identical environmental conditions.
*   **Statistical Evaluation:** The system calculates:

    $$\Psi_{\text{Asymmetry}} = \frac{\sum \text{Asasymmetrical Frames Selected}}{\sum \text{Total Selections}}$$

    A statistically significant increase in $\Psi_{\text{Asymmetry}}$ from Week 1 to Week 12 provides empirical evidence of the expertise-preference shift, demonstrating that the user has evolved past simple processing fluency to find aesthetic reward in complex visual structures .

### Experiment C: Forensic Temporal Calibration via Morellian Era Attribution
*   **Objective:** To verify if systematic training on minor, unconscious technical and physical artifacts (such as lens aberrations, film stock grain structure, and microphone placement styles) allows the user to accurately predict the decade of a film's production without knowing the title.
*   **Independent Variable:** Training on Morellian technical signatures vs. generic viewing.
*   **Dependent Variable:** Root Mean Square Error ($RMSE_{Era}$) of year predictions, and signal detection sensitivity ($d'$) for authentic vintage artifacts .
*   **Experimental Design (Interrupted Calibrated Prediction):**
    *   *Stimulus Pool:* 50 three-second, narrative-free clips (e.g., close-ups of walls, hands, or landscapes) extracted from the 150-film canon, spanning from 1930 to 2010.
    *   *Baseline Phase:* The user is shown 25 clips and must select the decade of production from a multiple-choice list.
    *   *Training Intervention:* The tutor conducts three 10-minute sessions highlighting Morellian technical signatures (e.g., how the introduction of high-speed color film stocks in the 1970s altered grain structures, or how early anamorphic lenses created specific edge-softness and barrel distortion).
    *   *Testing Phase:* The user is shown the remaining 25 clips and must select the decade of production, recording their predictions in a "predict-before-reveal" interface.
*   **Statistical Evaluation:** The program computes:

    $$RMSE_{\text{Era}} = \sqrt{\frac{1}{N}\sum_{i=1}^{N} (\hat{y}_i - y_i)^2}$$

    where $\hat{y}_i$ is the predicted production year and $y_i$ is the actual production year. A significant reduction in $RMSE_{\text{Era}}$ demonstrates the successful acquisition of forensic visual sensitivity.

---

## Evidence Grading and Epistemic Risk Assessment

This section evaluates the strength of the empirical evidence supporting the integration of these cognitive and pedagogical components into the tutoring agent.

| Tutoring System Component | Empirical Grade | Core Supporting Literature | Effect Size & Replication Data | Epistemic Risk of Film Translation |
| :--- | :--- | :--- | :--- | :--- |
| **Interleaved Category Induction** | **Robust** | Kornell & Bjork (2008) ; Kang & Pashler (2012) ; Birnbaum et al. (2013) . | Large, highly significant effects ($d_z = 0.43 - 0.48$); replicated in visual art , psychiatric case studies , and math . | **Low:** Director stylistic signatures function as visual categories similar to painters’ styles . |
| **Contrasting Cases before Telling** | **Robust** | Schwartz & Bransford (1998) ; Schwartz, Bransford, & Sears (2005) . | Significant improvements in conceptual transfer and structural feature recognition across multiple trials .
| **Low:** Technical shifts (e.g., focal length, lighting ratios) are highly suited to split-screen contrast pairings . |
| **Adaptive Comparative Judgment (ACJ)** | **Robust** | Pollitt (2012a, 2012b) ; Bramley (2015) ; Verhavert et al. (2019) . | High scale separation reliability ($0.89 - 0.95$); upward bias of adaptive pairing is statistically negligible ($<0.004$) . | **Medium:** Assumes that holistic relative choices of cinematic style can be consistently compared across a diverse 150-film canon . |
| **Perceptual Learning Modules (PLMs)** | **Robust** | Kellman, Massey, & Son (2010) ; Kellman & Massey (2013) ; Mettler, Massey, & Kellman (2016) . | Large, durable gains in structure extraction, visual search speed, and error reduction across varied training domains . | **Medium:** Assumes that speeded forced-choice classifications can capture dynamic, temporal edit structures . |
| **Morellian Style Attributions** | **Emerging** | Morellian forensic attribution models; eye-tracking validation studies. | Historically validated in art-attribution; human eye-tracking studies confirm longer fixation times on non-mimetic diagnostic details . | **High:** Assumes that directors execute technical details with the same level of unconscious, idiosyncratic consistency as painters’ hand-renderings. |
| **Expertise-Preference Shift** | **Emerging** | McWhinnie (1968) ; Leder et al. (2002) ; Reber, Schwarz, & Winkielman (2004) ; Williams et al. (2020) . | Replicated in static abstract geometry  and calligraphy ; neurological activation of motion areas during aesthetic processing . | **High:** Assumes that the preference shift from symmetry to asymmetry transfers from static visual art to dynamic film . |

---

1. How to Taste Wine — Wine Education | Sommy Wine Coach, (https://sommy.wine/learn/how-to-taste-wine/)
2. Wine: Frequently Asked Questions, (https://internationalwineauthority.com/wine-frequently-asked-questions/)
3. Blind Wine Tasting: A Complete Guide to its History, Science & Methods, (https://septimus.au/blind-wine-tasting-guide/)
4. In the Garden of Wine Economists - Oregon Wine Press, (https://www.oregonwinepress.com/in-the-garden-of-wine-economists)
5. How Valid and Reliable are Wine-Judging Events? Part 2, (https://theinquisitivevintner.wordpress.com/2018/03/20/how-valid-and-reliable-are-wine-judging-events-part-2/)
6. The fallacy of wine competitions; a ten year retrospective, (http://www.wine-economics.org/wp-content/uploads/2014/06/53-WW-2014-Hodgson.pdf)
7. Criteria for Accrediting Expert Wine Judges* | Journal of Wine Economics | Cambridge Core, (https://www.cambridge.org/core/journals/journal-of-wine-economics/article/criteria-for-accrediting-expert-wine-judges/EB1FE425E08BFDD0CB57F764158D5114)
8. Controversial Wine Judging Study: The Real Story | Wine-Searcher News & Opinion, (https://www.wine-searcher.com/m/2013/07/controversial-wine-judging-study-the-real-story)
9. The Distribution of Ratings Assigned to Blind Replicates* | Journal of Wine Economics, (https://www.cambridge.org/core/journals/journal-of-wine-economics/article/distribution-of-ratings-assigned-to-blind-replicates/BBF3DCCD599F587F4E7AE19F72EAE412)
10. Beyond Sight: The Influence of Opaque Glasses on Wine Sensory Perception - PMC, (https://pmc.ncbi.nlm.nih.gov/articles/PMC12469274/)
11. Beyond Sight: The Influence of Opaque Glasses on Wine Sensory Perception - Preprints.org, (https://www.preprints.org/manuscript/202508.1103)
12. Feldman's Method for Art Analysis | PDF | Composition (Visual Arts) | Vincent Van Gogh, (https://www.scribd.com/document/507792414/Feldmans-Method-Small)
13. Feldman Method in Art Criticism | PDF | Aesthetics | Knowledge - Scribd, (https://www.scribd.com/document/638622609/Untitled)
14. Teaching For Art Criticism: Incorporating Feldman's Critical Analysis Learning Model In Students' Studio Practice - ERIC, (https://files.eric.ed.gov/fulltext/EJ1086252.pdf)
15. Art History Warm-Ups - THAT ART TEACHER, (https://thatartteacher.com/2023/07/15/art-history-warm-ups/)
16. On the Emerging University and the Cult - CDN, (https://bpb-us-e2.wpmucdn.com/labs.utdallas.edu/dist/9/165/files/2026/06/On-the-Emerging-University-and-the-Cult.pdf)
17. Conservatory (CONSVTY) | University of Missouri-Kansas City Academic Catalog, (https://catalog.umkc.edu/course-offerings/graduate/consvty/)
18. Film in the Advanced Composition Classroom: A Tapestry of Style, (https://compositionforum.com/issue/32/film.php)
19. THOMPSON AND BORDWELL FILM HISTORY - webdisk.colegioamericano.edu.ec, (https://webdisk.colegioamericano.edu.ec/library/wMAANH4FE074/Thompson-And-Bordwell-Film-History)
20. David Bordwell - Wikipedia, (https://en.wikipedia.org/wiki/David_Bordwell)
21. A new look at the concept of style in film: the origins and development of the problem-solution model - Academia.edu, (https://www.academia.edu/343050/A_new_look_at_the_concept_of_style_in_film_the_origins_and_development_of_the_problem_solution_model)
22. The Psychophysics of Algebra: Mathematics Perceptual Learning Interventions Produce Lasting Changes in the Perceptual Encoding of Mathematical Objects - ResearchGate, (https://www.researchgate.net/publication/327957781_The_Psychophysics_of_Algebra_Mathematics_Perceptual_Learning_Interventions_Produce_Lasting_Changes_in_the_Perceptual_Encoding_of_Mathematical_Objects)
23. Perceptual Learning Modules in Mathematics: Enhancing Students' Pattern Recognition, Structure Extraction, and Fluency | Request PDF - ResearchGate, (https://www.researchgate.net/publication/227544864_Perceptual_Learning_Modules_in_Mathematics_Enhancing_Students'_Pattern_Recognition_Structure_Extraction_and_Fluency)
24. NCER 2011 and 2012 Awards - Institute of Education Sciences, (https://ies.ed.gov/ies/2025/01/ncer)
25. Why interleaving enhances inductive learning: The roles of discrimination and retrieval, (https://bjorklab.psych.ucla.edu/wp-content/uploads/sites/13/2016/07/Birnbaum_Kornell_EBjork_RBjork_inpress.pdf)
26. Testing the Interleaving Effect Without Response Bias: A Forced-Choice Reevaluation of Kornell & Bjork (2008) - PMC, (https://pmc.ncbi.nlm.nih.gov/articles/PMC13380076/)
27. Why interleaving enhances inductive learning: The roles of discrimination and retrieval, (https://www.researchgate.net/publication/233384444_Why_interleaving_enhances_inductive_learning_The_roles_of_discrimination_and_retrieval)
28. What Is the Mechanism Underlying the Interleaving Effect in Category Induction: An Eye-Tracking and Behavioral Study - Frontiers, (https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2021.770885/full)
29. On the Difficulty of Dislodging Learners' Illusions About How Best to Learn, (https://www.apa.org/pubs/highlights/spotlight/issue-70)
30. Creating a “time for telling” (Schwartz & Bransford, 1998), (https://mirjamglessmer.com/2022/08/20/creating-a-time-for-telling-schwartz-bransford-1998/)
31. PRACTICING VERSUS INVENTING WITH CONTRASTING CASES: THE EFFECTS OF TELLING FIRST ON LEARNING AND TRANSFER <Journal of Educat - AAA Lab, (https://aaalab.stanford.edu/assets/papers/2011/Practicing_versus_inventing.pdf)
32. Reconsidering Prior Knowledge Daniel L. Schwartz, David Sears, & Jammie Chang Stanford University Corresponding Author, (https://aaalab.stanford.edu/papers/Schwartz_Reconsidering_Prior_K.pdf)
33. How We Learn By Benedict Carey Chapter Summary - Bookey, (https://www.bookey.app/book/how-we-learn-by-benedict-carey)
34. Perceptual Learning Technology in Mathematics Education: Efficacy and Replication | IES, (https://ies.ed.gov/use-work/awards/perceptual-learning-technology-mathematics-education-efficacy-and-replication)
35. The Psychophysics of Algebra: Mathematics Perceptual Learning Interventions Produce Lasting Changes in the Perceptual Encoding of Mathematical Objects | JOV
| ARVO Journals, (https://jov.arvojournals.org/article.aspx?articleid=2700056)
36. (PDF) The effect of art expertise on visual symmetry and asymmetry preference, (https://www.researchgate.net/publication/363664916_The_effect_of_art_expertise_on_visual_symmetry_and_asymmetry_preference)
37. Psychology of Aesthetics: Overview of Theories | UKEssays.com, (https://www.ukessays.com/essays/psychology/psychology-aesthetics-overview-4500.php)
38. Aesthetic preference in the production of image sequences - PMC - NIH, (https://pmc.ncbi.nlm.nih.gov/articles/PMC10720618/)
39. The method of Adaptive Comparative Judgement - ResearchGate, (https://www.researchgate.net/publication/263381234_The_method_of_Adaptive_Comparative_Judgement)
40. (PDF) Examining the reliability of Adaptive Comparative Judgement (ACJ) as an assessment tool in educational settings - ResearchGate, (https://www.researchgate.net/publication/349543232_Examining_the_reliability_of_Adaptive_Comparative_Judgement_ACJ_as_an_assessment_tool_in_educational_settings)
41. Making evaluative legal judgements: law students' experiences of criteria-based scoring and comparative judgement - R Discovery, (https://discovery.researcher.life/article/making-evaluative-legal-judgements-law-students-experiences-of-criteria-based-scoring-and-comparative-judgement/0df3da5634a5352e958a1e676bac66ef)
42. Comparative Judgement: Is it 'Better' or 'Worse' than conventional assessment methods? | meridianvale, (https://meridianvale.wordpress.com/2016/12/09/comparative-judgement-is-it-better-or-worse-than-conventional-assessment-methods/)
43. (PDF) On 'Reliability' bias in ACJ - ResearchGate, (https://www.researchgate.net/publication/283318012_On_'Reliability'_bias_in_ACJ)
44. Using Adaptive Comparative Judgment in Writing Assessment: An Investigation of Reliability Among Interdisciplinary Evaluators - Scholarly Communication, (https://scholar.lib.vt.edu/ejournals/JOTS/v45/v45n1/pdf/baniya.pdf)
45. 1. Feeling Film Colours: Theoretical Framework - Open Book Publishers, (https://books.openbookpublishers.com/10.11647/obp.0380/ch1.xhtml)
46. Is spacing really the “friend of induction”? - PMC, (https://pmc.ncbi.nlm.nih.gov/articles/PMC3978334/)
47. The advantage of mixing examples in inductive learning: a comparison of three hypotheses, (https://www.tandfonline.com/doi/full/10.1080/01443410.2015.1127331)
48. Perceptual Learning in Jigsaw Puzzle | JOV - Journal of Vision, (https://jov.arvojournals.org/article.aspx?articleid=2141335)
49. Improvements in search efficiency (ms/item) as a function of PLM... - ResearchGate, (https://www.researchgate.net/figure/mprovements-in-search-efficiency-ms-item-as-a-function-of-PLM-training-Structure-and_fig3_250309986)
50. Aesthetic Judgment in Calligraphic Tracing: The Dominant Role of Dynamic Features - MDPI, (https://www.mdpi.com/2076-328X/15/4/525)
