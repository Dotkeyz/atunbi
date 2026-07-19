# Àtúnbí — Demo Flow

## Setup

- Open `http://localhost:3000` (or production URL)
- Log in as Dr. Ade
- Open QuickTime → New Screen Recording
- Mute notifications

---

## Intro (0:00–0:25)

> Hey — I'm Dotun. This is Àtúnbí. It's a Yoruba word. Means "reborn."

> So here's the thing. Most AI memory is basically a dumpster. Everything goes in, nothing comes out, nothing connects. The human brain doesn't work like that. You forget what doesn't matter. You hold onto what does. You notice when something contradicts what you thought you knew.

> That's what I tried to build. Every memory has to earn its life. If it doesn't — it either gets reborn into something useful, or it's gone. Let me walk you through it.

---

## Scene 1 — Ada (0:25–1:00)

**Type:**

```
Okay so Ada Chen is 54. She's got type 2 diabetes — on Metformin 500mg twice a day and Lisinopril for her blood pressure. Last HbA1c was 7.1, about three months ago. She's been telling me she's tired all the time, extra thirsty lately. I'm a bit concerned about adherence honestly. We're rechecking her labs today.
```

**Send.**

**While waiting, narrate:**

> So after a patient, I just talk through what I know. Thirty seconds, nothing formal. The system pulls out what matters.

**When response arrives, click Agent Trace. Show Query graph.**

> Look at this — five entities from one message. Ada, diabetes, metformin, lisinopril, HbA1c. They're not just stored as text. They're wired into a graph. So later when I ask "who's at risk for diabetes," the system already knows who's connected to what.

---

## Scene 2 — Lab results (1:00–1:25)

**Upload `Ada Blood Work — Q3 2026.pdf`.**

**While uploading:**

> Labs came back. Let me drop the PDF in.

**Type:**

```
what's changed in Ada's labs since last time?
```

**Send.**

**When response arrives, highlight the HbA1c jump:**

> 7.1 to 8.2. That's not good. She's getting worse. And the system pulled that straight from the PDF — it reads the actual text, doesn't guess at numbers. Important detail, took me a while to get that right.

---

## Scene 3 — Medication change (1:25–1:45)

**Type:**

```
Ada's HbA1c came back at 8.2 — that's up from 7.1, not great. I'm bumping her Metformin to 1000mg twice a day and starting her on Atorvastatin 20mg for lipids.
```

**Send.**

**When response arrives, click Agent Trace. Show the graph step with contradictions.**

> Metformin jumped from 500 to 1000. Atorvastatin is new. The system caught it. What's cool — the old dose isn't deleted, it's marked as superseded. So I can ask "what was she on before?" and it remembers.

---

## Scene 4 — Kai (1:45–2:10)

_Click New Chat to show cross-session recall._

**Type:**

```
New patient — Kai Rivera is 47, first time here. He's been dealing with fatigue for about three months, peeing a lot, dropped some weight without trying. Family history is worrying — his mom is diabetic, his brother got diagnosed at 42. He works nights so his eating habits aren't great. I'm sending labs but no meds yet.
```

**Send.**

**When response arrives, type:**

```
which patients have diabetes risk factors?
```

**Send.**

**When response arrives, click All Entities in the graph.**

> Now watch — Ada and Kai are in different conversations. Different sessions. But the system connected them. Family history. Night shifts. Symptoms. It didn't just store two patients. It built a relationship between them. That's the graph doing work that a search bar can't.

---

## Scene 5 — Architecture (2:10–2:40)

_Switch to architecture diagram._

> Quick look at what's under the hood. Five Qwen models — voice, vision, embeddings, scoring, extraction. Everything that comes in gets scored: how important, how often referenced, emotional weight. That score determines how long the memory lives.

> There's a Dream Phase that runs every night on Function Compute. Prunes the noise, summarizes the signal. Costs nothing when nobody's using it.

> Four memory tiers. Hybrid RRF search across all of them. The agentic loop rewrites your query, walks the entity graph, finds gaps. It's not just retrieving — it's reasoning about what it doesn't know yet.

---

## Close (2:40–3:00)

> Àtúnbí. It means reborn. I wanted to build memory that treats information like the brain does — not everything deserves to stick around. Some things grow. Some things go. That's it. Thanks for watching.
