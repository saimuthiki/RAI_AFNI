# RESPONSIBLE AI GOVERNANCE FRAMEWORK — WORKING BRIEF
### Prepared for: Sai Muthiki | Deliverable requested by: Kiran Devkar (AFNI)
### Purpose: Source document to be fed into a second model to auto-generate a polished PPT

---

## HOW TO USE THIS DOCUMENT

This file has four parts:

1. **PART A — Full meeting transcript** (verbatim, for reference/record).
2. **PART B — Meeting summary** (what was discussed and decided).
3. **PART C — Action items** (specifically what Sai owns, with detail).
4. **PART D — PPT blueprint** (slide-by-slide elements to cover, with the researched market content so the second model has everything it needs to build the deck).

When passing this to the PPT-generating model, you can tell it: *"Build a professional PowerPoint from PART D. Use PART B and PART C as context. Ignore PART A unless you need a direct quote."*

---

# PART A — FULL MEETING TRANSCRIPT (VERBATIM)

> Kiran Devkar (20:41): Okay, so Flasch also internally uses Python or it uses different language.
>
> Sai Muthiki (20:41): No, Python, Python, Python, same Python only.
>
> Kiran Devkar (20:41): OK. Okay, and so basically Streamlet is already using Python, Flasch is also using Python and Flasch API also. So I think it is.
>
> Sai Muthiki (20:41): Actually, one thing to clarify: Streamlit is for a normal basic UI stuff, but for when it comes to Fast API and Flasch, those will develop the API in background, the API calls and all, get calls, post calls, and all those will come in the back end, but when it comes to the front end, it will be on covers in the Streamlit. Streamlit and react are in the same base, and those both.
>
> Kiran Devkar (20:41): Sorry, say that again, say that again, Sai. Sorry, I interrupted.
>
> Sai Muthiki (20:41): No, Streamlit and React both comes under this front end frameworks, and when it comes to the back end, when where we are doing this API calls, right, those will be done using Flasch and Fast API.
>
> Kiran Devkar (20:41): Ohh yeah. Yeah, got it. Got you. Yeah, yeah, I think Streamlet obviously it is a UI and React is also a UI, but React, I don't think React uses, React is a totally different language as well, right? It's not Python, right?
>
> Sai Muthiki (20:42): It's not Python, it uses the JavaScript frameworks.
>
> Kiran Devkar (20:42): Correct, yeah, but Streamlet is uses Python, although it is friends framework, yeah.
>
> Sai Muthiki (20:42): Yes, yes, I mean, in the stream, we don't see any animation features, the basic UI, of course, we can do the navigation bars and the buttons and the layouts and the color coding, everything we can do, but when it comes to React, of course, yes, there are some lot of animations that we can do using React. And all, it will be completely different. The carousels that we can saw on the websites, those will be done using React.
>
> Kiran Devkar (20:42): Mm. And all these like Pandas and NumPy and TensorFlow and.
>
> Sai Muthiki (20:42): No. Those are all Python, Python only, those come under this data science background and all, analyzing data analytics background, those comes under. Matplotlib, random pipe and everything.
>
> Kiran Devkar (20:43): Yeah. Where, where, what is profit over here? Prophet and Presidio pirate.
>
> Sai Muthiki (20:43): Those are all normal Python only. Presidio, which means as in the earlier call we had discussed, for identifying the personal identifier information, just like for example, my name is Kiran and my son's SSN number is Santo, so it will detect the name and also the SSN number there. It will direct to the personally identified information. So that module comes from the Python itself. That's a framework, I mean, not a framework, it's a module from Python itself, inbuilt module. It will have a lot of customizations also. For example, in India, we do, for example, for the Aadhaar number. We do have 12 digit number. And for the US, there might be some other length of strings, right? We can customize according to our requirement. So that comes under Presidio. And Profanity is also same thing, where we can reduce all these profane words and all, and also this PyRIT one, right? This is for security tool. Like I said earlier, we are choosing one model to attack another model. One model acts as the attacker and another model is a target model. So the response is coming from the target model. We are using one more model like LLM as a judge, right? I think you know all these things, LLM as a judge. So it will judge whether the response is profane or it will consider any kind of hate speech or is it something like illegal kind of thing it will contain. It will check all these things. And based on that, we will check the LLM vulnerability testing. It comes under testing purpose like how trustworthy that model is all about and is it reliable or not? Something like that. It's actually a framework, PyRIT.
>
> Kiran Devkar (20:45): Okay. Good. So I'm actually interested in one of your earlier discussion that you mentioned last time about you did something at the Apple, right, regarding the responsible AI. LLM security project.
>
> Sai Muthiki (20:45): Yes.
>
> Kiran Devkar (20:45): Yeah, in my role over here, I'm like very much focused on overall AI governance and how do we build or how do we develop a framework for enabling the AI governance here internally at AFNI. And so I think a lot of similarities would be there, so... Did you use any kind of like SHAP or anything in that LLM security project for Apple?
>
> Sai Muthiki (20:46): No, SHAP I didn't use.
>
> Kiran Devkar (20:46): No, I mean, there are some responsible AI frameworks, right?
>
> Sai Muthiki (20:46): Sorry, this one, right? Explainability, I mean, you mean SHAP, right? That is part of some explainability. There are a lot more bunch of modules, like in the fairness, we do have AIF 360, and in the explainability part, we do see some SHAP techniques and all, these all come under these various tenets.
>
> Kiran Devkar (20:46): Correct, correct.
>
> Sai Muthiki (20:46): There are some tenets when it comes to this responsible AI, mostly like something like privacy. That is one thing that we already discussed, right? Presidio and not only Presidio, there are other modules and also we are using predefined and pre-trained models from Hugging Face also to identify the personal identifiable information. That comes under privacy. And when it comes to profanity, there is one, this is also same thing. It can be done by using normal Python frameworks and also some Hugging Face modules, the pre-trained modules, which is well enough in finding the profane words. That comes under profanity and explainability, same thing. And security and fairness and bias and hallucination. That is one more thing. And there is one more thing I didn't remember, but there are some six to seven tenets such like that. All come under responsible AI. We built a tool in my previous company, which we called it as responsible AI toolkit. It will come up with all these things. All the six tenets or 7 tenets will be covered in this same toolkit.
>
> Kiran Devkar (20:47): Good. I think when you implemented the responsible AI right for security, how did you go forward with that? Did you use like Azure or AWS or any cloud or it was totally like open source security frameworks?
>
> Sai Muthiki (20:47): Yes. There for model testing and all, we had used Azure only, I mean Azure hosted models only. But there are some third party tools also we had used there. Those are open source models from Hugging Face itself. See for each and every module we had used a separate set of models which are well enough in detecting the PII entities and the profane words and some other stuff, the illegal hate speech stuff. So those are well enough in doing all those things and we had compared that time. We had parallelly implemented Azure. There is one service in Azure itself.
>
> Kiran Devkar (20:49): And also... something that is relevant and we should gain trust of the market. Like when we launch any products which are AI enabled products or AI enabled tools or products, we sometimes also demonstrate to clients, right? And so, and we need to go through some security and approval from the client side as well. So what I'm trying to establish here internally is while doing that AI native development, we want to take care of responsible AI architecture for any application that we are developing in AI.
>
> Sai Muthiki (20:50): Okay.
>
> Kiran Devkar (20:50): So I think what probably I think you can contribute is come up like two, three options that are there in the market, which some of it you might have used, some of it could be new or modern, which you might have not used. And then we can weigh in about what approach we can follow over here. So any applications that we develop which are AI native going forward will need to follow the responsible AI framework in this way, right? So it could use SHAP, it could use something like Azure guardrails that you are saying, or if it makes sense to use like customized guardrails that we want to enable. I have not yet thought of on Nemo guardrails yet. But I'm open for if it has value in it, maybe we can weigh that as well. So, at this point, I think we are all fresh. There is certain that we have established, like anything that we use is using Azure, and we are not tied up with anything, as long as the AI that we are implementing is secured and stays private, is cognizant about all the data, can explain what it does internally, be transparent. I think there are five principles, right, that they talk about, like the fairness and reliability, the security and privacy, the transparency, the, what are the other two? Sorry, I think, so we talk.
>
> Sai Muthiki (20:52): privacy, profanity, explainability, fairness and bias, and security, and one more thing, hallucinations.
>
> Kiran Devkar (20:52): Yeah, got it. Right. So all these things, like how do we tackle each one of them with our own strategic approach, right? That's something that I'm actually very much keen on doing. So while your access and everything is being worked upon, maybe you can put... Is it feasible for you to put up like one or two slides or one or two doc, like a one pager or two pager document showing the solution thinking about what we can do on a one or two pager and then you and I can walk through and establish some framework over here internally.
>
> Kiran Devkar (20:53): ...the other implementation, which are also important. So both are important. I think we can start with that and you can get involved in some of the other things as well. So I'm just thinking what could be feasible right now, right, with you.
>
> Sai Muthiki (20:53): Okay, okay, I'll do that. I'll prepare a document or else a PPT which compares all the open source modules and the partner or the paid modules. I'll do a thorough research on these things, okay?
>
> Kiran Devkar (20:54): Okay, and whatever you have implemented and experience as well, I mean, we can see whatever works over here.
>
> Sai Muthiki (20:54): Okay, sure.
>
> Kiran Devkar (20:54): You are already 102 certified, right?
>
> Sai Muthiki (20:54): Yes.
>
> Kiran Devkar (20:54): Okay, that's good. So 102 and 103, you felt it is similar or 103 is... 103 different.
>
> Sai Muthiki (20:54): It's a kind of a similar thing, Kiran. Like, there are some, here we do have focused on mostly the AI agents part and also the UI is also different. Apart from the UI. Earlier, we do have some Azure AI engineering and now it is something like Azure AI applications and agent TK, mostly those are focused on. Mostly those are the things and I need to cover a few more topics and work with some around 10 to 15 articles. So once that is done, I am good to go to attempt this AI-103 also, but I'm planning to complete that in this weekend only.
>
> Kiran Devkar (20:55): Okay.
>
> Sai Muthiki (20:55): Earlier it is something like Azure AI search and now it is something like the relevant knowledge RAG and scenarios and file search also they had enabled and there are some SDKs also that they had provided to us. So yeah, there are some couple of changes. Of course.
>
> Kiran Devkar (20:55): But you think that one week is comfortable to prepare for 103 or?
>
> Sai Muthiki (20:55): No, actually I started six days ago. So I'm comfortable. Yeah, yes.
>
> Kiran Devkar (20:55): Okay, how much time it took for you for 102 then? Like one or two weeks or took more?
>
> Sai Muthiki (20:55): No, AI-102 I completed in when I'm in the previous company there we do and they had provided some vouchers and all so we utilized the vouchers for this completion of certifications. Like they are AI-900 and AI-102. But now those two certifications got updated and we do have version C like AI-901 instead of 900 and 102 to 103. So those two are some advanced version. They had added few more modules into it.
>
> Kiran Devkar (20:56): I think they retired already, right? Or no, I don't know.
>
> Sai Muthiki (20:56): Yes, yes. That's why I'm trying to skill up myself. AI-103.
>
> Kiran Devkar (20:56): No, that's good. So, we'll do one discussion once you get a chance to put down those frameworks or solution what you think we can do for enabling responsible AI framework here at AFNI. I think, whether it is later this week or early next week, I'm good, like whatever time you need right for. But put that to pages, OK?
>
> Sai Muthiki (20:57): Yeah, actually, let Yamini invite when we are comfortable with this, the for further follow up meeting. OK, then I will schedule.
>
> Kiran Devkar (20:57): Yeah, just remind her to send me the acceptable use and I will take care of the rest then.
>
> Sai Muthiki (20:57): Okay, surely, I'll do that.
>
> Kiran Devkar (20:57): OK, sounds good. I appreciate Sai today. Thank you.
>
> Sai Muthiki (20:57): Yeah, thank you so much, Kiran.

---

# PART B — MEETING SUMMARY

**Context.** This was a technical + strategic discussion between Kiran Devkar (AFNI, focused on internal AI governance) and Sai Muthiki. The first half clarified the technology stack (Python across the board for Streamlit UI, Flask/FastAPI backends; React as the JavaScript-based frontend alternative; Pandas/NumPy/TensorFlow/Matplotlib as Python data-science libraries). Sai explained several responsible-AI-relevant tools: **Presidio** (PII detection, customizable per-region — e.g., US SSN vs India Aadhaar), **profanity filtering** (Python + Hugging Face pre-trained models), and **PyRIT** (Microsoft's red-teaming / LLM vulnerability framework using an attacker-model vs target-model setup with an LLM-as-a-judge).

**The core ask.** Kiran wants to establish an **internal Responsible AI governance framework at AFNI** that every AI-native application must follow going forward. The driver is twofold: (1) build trustworthy AI internally, and (2) pass client-side security and approval reviews when AFNI demonstrates or ships AI-enabled products.

**Key positioning agreed:**
- AFNI's default cloud is **Azure**, but they are **not locked in** to any single vendor.
- The framework must ensure AI is **secure, private, data-aware, explainable, and transparent**.
- Sai referenced building a **"Responsible AI Toolkit"** at his previous company covering 6–7 tenets.
- The tenets discussed: **Privacy, Profanity, Explainability, Fairness & Bias, Security, Hallucination** (plus accountability/transparency/reliability from broader frameworks).
- Kiran named candidate technologies to weigh: **SHAP** (explainability), **Azure guardrails / Azure AI Content Safety**, **custom guardrails**, and **NeMo Guardrails** (open to it if it adds value).

**The deliverable.** Sai committed to producing a **document or PPT** that compares **open-source modules vs. partner/paid modules** for each responsible-AI tenet, incorporating both his prior hands-on experience and fresh market research, so he and Kiran can walk through it and establish AFNI's internal framework.

**Side items.** Sai is preparing for the Azure **AI-103** certification (already holds AI-102), targeting completion this weekend. A follow-up meeting will be scheduled via Yamini; Sai will remind Yamini to send Kiran the **acceptable use** document.

---

# PART C — ACTION ITEMS (SAI'S OWNERSHIP)

**Primary deliverable — the comparison deck/document:**
1. Produce a PPT (with an optional 1–2 page doc backup) that maps **each responsible-AI tenet** to concrete tooling options.
2. For every tenet, present **open-source options vs. paid/partner (cloud) options**, with pros, cons, and a recommendation.
3. Weave in **Sai's own hands-on experience** (the Apple LLM-security project, the previous-company Responsible AI Toolkit, Presidio/PyRIT/profanity work).
4. Cover the technologies Kiran specifically named so he sees them addressed: **SHAP, Azure AI Content Safety (guardrails), custom guardrails, NeMo Guardrails**.
5. Keep an **Azure-first but vendor-neutral** framing (Azure is default; not locked in).
6. Frame everything toward **two goals: internal trust + passing client security/approval reviews**.
7. End with a **recommended AFNI framework** and a walkthrough-ready structure so Kiran can co-establish the standard.

**Secondary / logistics:**
8. Remind **Yamini** to (a) schedule the follow-up meeting once the deck is ready, and (b) send Kiran the **acceptable use** document.
9. Complete **Azure AI-103** certification (target: this weekend).

**Tone to aim for (to outperform expectations):** don't just list tools — show a *decision framework* (when to pick open-source vs. paid, per tenet), tie each tenet to a real AFNI risk, and give a phased adoption roadmap. That is what turns "a comparison" into "a governance standard," which is what Kiran actually wants.

---

# PART D — PPT BLUEPRINT (SLIDE-BY-SLIDE, WITH RESEARCHED CONTENT)

> The second model can turn each numbered block below into one or more slides. Content is already researched and populated so the PPT model doesn't have to invent facts.

## Slide 1 — Title
**Responsible AI Governance Framework for AFNI**
Subtitle: *A tenet-by-tenet standard for AI-native application development — open-source vs. cloud-native tooling*
Presenter: Sai Muthiki | Audience: Kiran Devkar & AFNI AI Governance

## Slide 2 — Why This Matters (Business Context)
- AFNI is moving to AI-native development; every AI app should follow one governance standard.
- Two drivers: (1) internal trustworthy AI, (2) passing **client security & approval reviews** before demos/shipping.
- Regulatory backdrop (2026): the **EU AI Act's high-risk obligations apply from August 2, 2026**; **NIST AI Risk Management Framework** is the de-facto US reference; **ISO/IEC 42001** turns AI ethics into a certifiable management system. Clients increasingly ask which framework a vendor follows.
- Principle: **Azure-first, but vendor-neutral** — pick the best control per tenet, not one monolith.

## Slide 3 — What "Responsible AI" Means (The Tenets)
Industry frameworks (NIST AI RMF, EU AI Act/ALTAI, OECD, Microsoft RAI Standard v3, Cisco, IBM) label things differently but converge on a common set. AFNI's working tenets:
1. **Privacy & Data Governance** (PII protection)
2. **Security** (adversarial robustness, red-teaming, prompt-injection defense)
3. **Fairness & Bias**
4. **Explainability & Transparency**
5. **Profanity / Content Safety** (toxicity, hate speech, harmful content)
6. **Hallucination / Reliability & Groundedness**
7. **Accountability** (ownership, audit trails, logging) — the "glue" tenet.
> Note: NIST's "trustworthy AI" = valid & reliable, safe, secure & resilient, accountable & transparent, explainable & interpretable, privacy-enhanced, and fair with harmful bias managed. Good to cite for credibility.

## Slide 4 — Framework Architecture (Where Controls Live)
Two enforcement patterns to present as a diagram:
- **Gateway-layer guardrails** (one enforcement point in front of all model calls — consistent policy across providers/clouds). Good for multi-cloud consistency.
- **Library/in-app guardrails** (validation inside the application — conversational flows, structured-output checks). Good for app-specific logic.
- Recommend **defense-in-depth**: input rails → model → output rails, plus offline testing (red-teaming) in CI/CD. Most production teams combine 2–3 tools rather than one.
- Map to standards: this pattern aligns with the **OWASP Top 10 for LLM Applications** and **NIST AI RMF**.

## Slide 5 — TENET 1: Privacy / PII
**Open-source:** **Microsoft Presidio** (PII detection & anonymization; customizable recognizers per region — US SSN, India Aadhaar 12-digit, etc.); **Hugging Face** pre-trained NER models for entity detection.
**Cloud/paid:** **Azure AI Language – PII detection service**; Azure guardrails ship **PII redaction as pre-call and post-call** filtering.
**AFNI recommendation:** Presidio for customizable, on-prem/in-app redaction; Azure PII service where Azure-native pipelines already exist. Privacy-by-design: data minimization, consent capture, retention policies, runtime redaction.
**Sai's experience hook:** Presidio customization work (SSN vs Aadhaar), Hugging Face models used per-entity.

## Slide 6 — TENET 2: Security (Red-Teaming & Guardrails)
**Red-teaming / vulnerability testing (offline):** **Microsoft PyRIT** — attacker-model vs target-model with **LLM-as-a-judge** to score profanity/hate/illegal content and assess model vulnerability & trustworthiness.
**Runtime guardrails — open-source:** **NVIDIA NeMo Guardrails** (Apache 2.0; Colang DSL; input/output/dialog/tool-use rails; integrates with LangChain/LangGraph/LlamaIndex); **LLM Guard** by Protect AI (prompt & response sanitization, chainable scanners); **Guardrails AI** (composable validators, strong for structured output); **Meta Llama Guard 4** / **Prompt Guard 2** (LLM-based content & injection classification, multimodal); **Lakera Guard**.
**Runtime guardrails — cloud/paid:** **Azure AI Content Safety** (Azure AI Foundry; REST/SDK; **Prompt Shields** for jailbreak & indirect prompt injection; groundedness detection; custom blocklists); **AWS Bedrock Guardrails**; **GA Guard** (adversarially trained).
**Important nuance to include (credibility booster):** cloud content-safety tools are strongest *within their own platform*; independent benchmarks show a large **adversarial-robustness gap** (e.g., Azure AI Content Safety scored notably lower F1 on adversarial inputs than Bedrock or specialized guards). Takeaway: **combine** a gateway guard + specialized injection classifier rather than relying on one cloud filter.
**AFNI recommendation:** NeMo Guardrails (programmable, vendor-neutral) + Azure Content Safety (Azure-native) + PyRIT for pre-deployment red-teaming in CI/CD.
**Sai's experience hook:** the Apple LLM-security project; PyRIT attacker/target/judge setup.

## Slide 7 — TENET 3: Fairness & Bias
**Open-source:** **IBM AI Fairness 360 (AIF360)** (comprehensive metrics + mitigation: reweighing, adversarial debiasing, correlation removal, exponential-gradient; Python/R); **Microsoft Fairlearn** (assessment + mitigation, easy Azure ML integration, model-comparison dashboard); **What-If Tool**; **FairML**.
**Cloud/paid:** **Fiddler AI**, **Arthur AI** (real-time fairness monitoring); **DataRobot Bias & Fairness Toolkit**; **Truera / Monitaur** (compliance-first for regulated industries).
**AFNI recommendation:** Fairlearn (Azure-aligned) for standard cases; AIF360 where deep metric coverage/mitigation is needed; a monitoring vendor only if AFNI needs real-time production drift/bias alerts.
**Sai's experience hook:** AIF360 referenced in the meeting.

## Slide 8 — TENET 4: Explainability & Transparency
**Open-source:** **SHAP** (game-theory feature importance), **LIME** (local model-agnostic explanations), **IBM AI Explainability 360 (AIX360)** (tabular/text/image/time-series), **InterpretML** (bundles SHAP/LIME), **Alibi**, **ELI5**.
**Cloud/paid:** **Azure ML responsible-AI dashboard** (InterpretML-based); vendor observability platforms (Fiddler, Arthur).
**AFNI recommendation:** SHAP + LIME as the baseline; AIX360/InterpretML for richer explanation types; surface explanations in the Azure RAI dashboard for client-facing transparency.
**Sai's experience hook:** SHAP (the tool Kiran asked about by name) — good to address directly.

## Slide 9 — TENET 5: Profanity / Content Safety
**Open-source:** Python profanity libraries + **Hugging Face** pre-trained toxicity/hate-speech classifiers; **Llama Guard 4**; scanners inside **LLM Guard**.
**Cloud/paid:** **Azure AI Content Safety** (text/image moderation across severity categories); **OpenAI Moderation**.
**AFNI recommendation:** Hugging Face classifiers for customizable, cost-free filtering in-app; Azure Content Safety for managed multimodal moderation.
**Sai's experience hook:** profanity filtering via Python + Hugging Face pre-trained models.

## Slide 10 — TENET 6: Hallucination / Groundedness & Reliability
**Open-source / techniques:** RAG grounding + citation checking; **Guardrails AI** validators for factual/structured checks; groundedness evaluators; LLM-as-a-judge scoring.
**Cloud/paid:** **Azure AI Content Safety – groundedness detection** (verifies outputs against source documents); observability platforms (Fiddler, Arthur, Galileo, Maxim) for hallucination monitoring.
**AFNI recommendation:** RAG + groundedness detection + output rails; automated eval harness in CI/CD.

## Slide 11 — TENET 7: Accountability (Governance Layer)
- Named owner per AI system; **audit trails & logging** for every model change and outcome; version control; automated alerts for model degradation / bias drift; secure model serving with access controls.
- Data-ingestion governance: data quality, balance, privacy.
- Regulators want *evidence* that runtime controls existed and were tested — logging is not optional.

## Slide 12 — Consolidated Comparison Matrix (Open-Source vs. Cloud/Paid)
Present as a table. Columns: **Tenet | Open-Source Option(s) | Cloud/Paid Option(s) | AFNI Recommendation | Sai's Prior Use**.
| Tenet | Open-Source | Cloud / Paid | AFNI Recommendation | Prior Use |
|---|---|---|---|---|
| Privacy / PII | Presidio, HF NER | Azure AI Language PII | Presidio + Azure PII | Yes |
| Security / Guardrails | NeMo, LLM Guard, Guardrails AI, Llama Guard | Azure Content Safety (Prompt Shields), Bedrock, GA Guard | NeMo + Azure CS + PyRIT | Yes (Apple) |
| Red-Teaming | PyRIT | (Azure-hosted models) | PyRIT in CI/CD | Yes |
| Fairness & Bias | AIF360, Fairlearn | Fiddler, Arthur, DataRobot | Fairlearn + AIF360 | Yes (AIF360) |
| Explainability | SHAP, LIME, AIX360, InterpretML | Azure ML RAI dashboard | SHAP+LIME+AIX360 | Referenced |
| Profanity / Content | HF classifiers, Llama Guard | Azure Content Safety, OpenAI Moderation | HF + Azure CS | Yes |
| Hallucination | RAG + Guardrails AI, LLM-as-judge | Azure groundedness detection | RAG + groundedness + rails | Partial |
| Accountability | MLflow logging, custom audit | Azure ML governance | Logging + audit trails | — |

## Slide 13 — Decision Framework (When Open-Source vs. When Paid)
- **Open-source when:** need deep customization, vendor-neutrality, cost control, in-app logic, or region-specific rules (e.g., Aadhaar).
- **Cloud/paid when:** need managed SLAs, multimodal coverage, real-time monitoring, or fast client-facing compliance evidence.
- **Both when:** enterprise scale — gateway guard for consistency + in-app validators for logic (common 2026 pattern).

## Slide 14 — Recommended AFNI Framework (The Standard)
- **Mandatory controls per AI-native app:** PII redaction, input/output guardrails, red-team test in CI/CD, explainability report, content-safety filter, groundedness check, audit logging.
- **Azure-first, vendor-neutral** enforcement at a gateway layer.
- Reusable internal **"AFNI Responsible AI Toolkit"** (echoing Sai's prior-company toolkit) bundling all seven tenets.
- Aligned to **NIST AI RMF + OWASP LLM Top 10 + EU AI Act** so client reviews pass.

## Slide 15 — Adoption Roadmap (Phased)
- **Phase 1 (0–30 days):** pilot Presidio + Azure Content Safety + SHAP on one AI app; define mandatory-control checklist.
- **Phase 2 (30–60 days):** add NeMo Guardrails gateway + PyRIT red-teaming in CI/CD; stand up audit logging.
- **Phase 3 (60–90 days):** add Fairlearn/AIF360 + groundedness monitoring; publish the AFNI RAI standard; produce client-facing compliance one-pager.

## Slide 16 — Next Steps
- Walkthrough of this deck with Kiran; finalize AFNI standard.
- Yamini to schedule follow-up + send Kiran the **acceptable use** document.
- Sai to complete **Azure AI-103** certification.

---

## SOURCES USED FOR MARKET RESEARCH (for your reference; you can drop or footnote these)
- Openlayer — Responsible AI Framework Implementation Guide (June 2026): NIST AI RMF, Microsoft RAI Standard v3, Cisco framework, common tenets.
- Atlan — NIST / EU AI Act / OECD comparison (2026): trustworthy-AI definition, deployer obligations.
- FutureAGI — AI Ethics Frameworks 2026: EU AI Act enforcement from Aug 2, 2026; ISO/IEC 42001; privacy-by-design; IBM AIF360/AIX360; Microsoft Fairlearn/InterpretML.
- Cisco Responsible AI Framework: six principles (transparency, fairness, accountability, privacy, security, reliability).
- Galileo / Maxim AI / General Analysis / AI Sec Bench — 2026 guardrails comparisons: NeMo, Azure AI Content Safety (Prompt Shields), Guardrails AI, LLM Guard, Llama Guard 4, Bedrock, GA Guard; adversarial-robustness benchmark gap; OWASP LLM Top 10.
- Medium/Cylynx, VerifyML, Towards Data Science, Turing Post, ai-fairness-360.org — fairness/explainability tooling: AIF360, Fairlearn, SHAP, LIME, AIX360, InterpretML, Fiddler, Arthur, DataRobot, Truera, Monitaur.
