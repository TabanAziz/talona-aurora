# Feature map

This map follows the product implementation in this repository. The overview shows the working flow; the detailed diagrams keep the individual capabilities readable rather than putting more than a hundred boxes on one canvas. Each feature links to its implementation, and the inventory below each diagram states what is needed to use it.

The supplied atlas contained 110 entries. This version maps 109 of those entries to code in the public repository and adds 12 capabilities from the newer project experience and data preparation. The former standalone chat-export audit is excluded because its implementation is not shipped here. The old QR deployment utility is also absent, but its user-facing behaviour is implemented by the current label URL helper and frontend build setting.

The inventory is a source-level check of implementation and integration points, not a claim that every feature was rerun against a live service. A configured channel, a simulated machine and a view awaiting evidence are different states. There is no blanket completion percentage.

## The working flow

```mermaid
flowchart TB
    SETUP["Reviewed project import"]:::workspace --> CONTEXT["Rooms, teams, drawings and tasks"]:::workspace
    EMAIL["Email revision"]:::channels --> EVENT["Incoming message"]:::channels
    VOICE["Telegram voice note"]:::channels --> EVENT
    EVENT --> INTERPRET["Transcribe, confirm and extract"]:::intelligence
    INTERPRET --> RECORD["Record and source evidence"]:::intelligence
    CONTEXT --> RECORD
    RECORD --> DRAWING["Revision comparison"]:::drawings
    RECORD --> RULES["Drawing, inspection and resource checks"]:::intelligence
    DRAWING --> RULES
    RULES --> PROPOSAL["Calculated impact and proposal"]:::intelligence
    PROPOSAL --> HUMAN["Reviewed decision"]:::interface
    HUMAN --> RESULT["Updated work state and notices"]:::channels
    RECORD --> GATE["Task-level start check"]:::intelligence
    RESULT --> GATE
    GATE --> EQUIPMENT["Simulated robot or drone"]:::interface
    RESULT --> VIEWS["Overview, schedule and reports"]:::interface
    DRAWING --> VIEWS
    classDef channels fill:#eaf3fc,stroke:#3575ad,color:#17324d
    classDef intelligence fill:#fff1df,stroke:#b77929,color:#553711
    classDef drawings fill:#e8f5f0,stroke:#33836d,color:#163f35
    classDef interface fill:#f0eefb,stroke:#7763b1,color:#32244f
    classDef workspace fill:#edf4f4,stroke:#397d80,color:#173f42
```

Solid arrows above show data or decision flow. In the detailed diagrams below, dotted lines only group related capabilities for reading. They do not assert that every connected feature must execute before the next one. The reference codes provide a stable way to match entries to the supplied atlas; W references identify newer additions.

## Reading availability

- **Implemented:** the view or module is present; it still uses the selected project's data.
- **Relevant evidence / state:** the feature becomes meaningful after a message, change, decision or proposal exists.
- **Configuration / external service:** credentials, routing or an optional service are required for the live path.
- **Simulation / structured observation:** equipment is simulated, or an API accepts measured fields; physical hardware is not supplied.

The [demo walkthrough](DEMO.md#finding-the-other-views) gives the exact English navigation labels. The [architecture](ARCHITECTURE.md) explains the boundaries between interpretation, calculation and execution.

## Project setup, import and example data

```mermaid
flowchart TB
    W01["Project catalog and<br/>selection"]:::workspace
    W02["Recoverable project<br/>deletion"]:::workspace
    W03["Reviewed structured project<br/>import"]:::workspace
    W04["Validated multi-floor<br/>geometry"]:::workspace
    W05["Drawing register and<br/>revision selection"]:::workspace
    W06["Building, floor and full-<br/>screen controls"]:::workspace
    W07["Explicit project channel<br/>assignment"]:::workspace
    W08["Visible message-processing<br/>stages"]:::workspace
    W09["Description-based project<br/>branding"]:::workspace
    W10["Prepare missing robot<br/>layout tasks"]:::workspace
    W11["Adaption synthetic-message<br/>augmentation"]:::workspace
    W12["Reproducible hotel source<br/>package"]:::workspace
    W01 -.-> W02
    W01 -.-> W03
    W02 -.-> W04
    W02 -.-> W05
    W03 -.-> W06
    W03 -.-> W07
    W04 -.-> W08
    W04 -.-> W09
    W05 -.-> W10
    W05 -.-> W11
    W06 -.-> W12
    classDef workspace fill:#edf4f4,stroke:#397d80,color:#173f42
    click W01 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/projects/index.tsx" "Open implementation"
    click W02 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/workspace/storage.py" "Open implementation"
    click W03 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/workspace/importer.py" "Open implementation"
    click W04 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/workspace/geometry.py" "Open implementation"
    click W05 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/drawings/Drawings.tsx" "Open implementation"
    click W06 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/drawings/GeometryView.tsx" "Open implementation"
    click W07 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/workspace/channels.py" "Open implementation"
    click W08 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/overview/Activity.tsx" "Open implementation"
    click W09 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/workspace/branding.py" "Open implementation"
    click W10 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/workspace/robot_programme.py" "Open implementation"
    click W11 "https://github.com/TabanAziz/talona-aurora/tree/main/adaption/generate.py" "Open implementation"
    click W12 "https://github.com/TabanAziz/talona-aurora/tree/main/docs/demo-data/Aurora_Project_EN.json" "Open implementation"
```

| Ref | Capability | Implementation | Availability |
|---|---|---|---|
| W01 | Project catalog and selection | [index.tsx](../frontend/src/pages/projects/index.tsx) | Implemented |
| W02 | Recoverable project deletion | [storage.py](../backend/app/workspace/storage.py) | Implemented |
| W03 | Reviewed structured project import | [importer.py](../backend/app/workspace/importer.py) | Live setup model for new analysis |
| W04 | Validated multi-floor geometry | [geometry.py](../backend/app/workspace/geometry.py) | Supplied geometry or reviewed assumptions |
| W05 | Drawing register and revision selection | [Drawings.tsx](../frontend/src/pages/drawings/Drawings.tsx) | Implemented |
| W06 | Building, floor and full-screen controls | [GeometryView.tsx](../frontend/src/pages/drawings/GeometryView.tsx) | Geometry and WebGL |
| W07 | Explicit project channel assignment | [channels.py](../backend/app/workspace/channels.py) | Configured email / Telegram accounts |
| W08 | Visible message-processing stages | [Activity.tsx](../frontend/src/pages/overview/Activity.tsx) | Incoming processing activity |
| W09 | Description-based project branding | [branding.py](../backend/app/workspace/branding.py) | Configured setup model |
| W10 | Prepare missing robot layout tasks | [robot_programme.py](../backend/app/workspace/robot_programme.py) | Imported project and live setup model |
| W11 | Adaption synthetic-message augmentation | [generate.py](../adaption/generate.py) | Offline data preparation; service key to regenerate |
| W12 | Reproducible hotel source package | [Aurora_Project_EN.json](../docs/demo-data/Aurora_Project_EN.json) | Synthetic example |

## Communication · 1

```mermaid
flowchart TB
    F49["Recipient directory and<br/>channel delivery"]:::channels
    F18["Telegram channel"]:::channels
    F19["Email channel"]:::channels
    F20["Voice transcription"]:::channels
    F22["Deliver changes and track<br/>confirmations"]:::channels
    F30["WhatsApp channel through<br/>Twilio"]:::channels
    F58["Escalation for unconfirmed<br/>changes"]:::channels
    F59["Interpret confirmation<br/>read-backs"]:::channels
    F60["Confirmation read-back flow"]:::channels
    F61["Crew-language messages"]:::channels
    F78["Spoken crew briefings"]:::channels
    F89["Visible transcription<br/>failures"]:::channels
    F49 -.-> F18
    F49 -.-> F19
    F18 -.-> F20
    F18 -.-> F22
    F19 -.-> F30
    F19 -.-> F58
    F20 -.-> F59
    F20 -.-> F60
    F22 -.-> F61
    F22 -.-> F78
    F30 -.-> F89
    classDef channels fill:#eaf3fc,stroke:#3575ad,color:#17324d
    click F49 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/live" "Open implementation"
    click F18 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/telegram" "Open implementation"
    click F19 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/email" "Open implementation"
    click F20 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/voice" "Open implementation"
    click F22 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/outbox" "Open implementation"
    click F30 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/whatsapp" "Open implementation"
    click F58 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/outbox" "Open implementation"
    click F59 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/readback" "Open implementation"
    click F60 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/outbox" "Open implementation"
    click F61 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/language" "Open implementation"
    click F78 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/speech" "Open implementation"
    click F89 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/voice" "Open implementation"
```

| Ref | Capability | Implementation | Availability |
|---|---|---|---|
| F49 | Recipient directory and channel delivery | [live](../backend/app/live) | Configuration / external service |
| F18 | Telegram channel | [telegram](../backend/app/telegram) | Configuration / external service |
| F19 | Email channel | [email](../backend/app/email) | Configuration / external service |
| F20 | Voice transcription | [voice](../backend/app/voice) | Configuration / external service |
| F22 | Deliver changes and track confirmations | [outbox](../backend/app/outbox) | Relevant project evidence / state |
| F30 | WhatsApp channel through Twilio | [whatsapp](../backend/app/whatsapp) | Configuration / external service |
| F58 | Escalation for unconfirmed changes | [outbox](../backend/app/outbox) | Configuration / external service |
| F59 | Interpret confirmation read-backs | [readback](../backend/app/readback) | Configuration / external service |
| F60 | Confirmation read-back flow | [outbox](../backend/app/outbox) | Configuration / external service |
| F61 | Crew-language messages | [language](../backend/app/language) | Configuration / external service |
| F78 | Spoken crew briefings | [speech](../backend/app/speech) | Configuration / external service |
| F89 | Visible transcription failures | [voice](../backend/app/voice) | Relevant project evidence / state |

## Communication · 2

```mermaid
flowchart TB
    F91["Mark mail read after<br/>ingestion"]:::channels
    F121["Confirm voice transcripts<br/>before use"]:::channels
    F151["Shared-secret Telegram<br/>webhook"]:::channels
    F181["Prompt Telegram receipt and<br/>drop reporting"]:::channels
    F91 -.-> F121
    F91 -.-> F151
    F121 -.-> F181
    classDef channels fill:#eaf3fc,stroke:#3575ad,color:#17324d
    click F91 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/email" "Open implementation"
    click F121 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/voicecheck" "Open implementation"
    click F151 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/telegram" "Open implementation"
    click F181 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/telegram" "Open implementation"
```

| Ref | Capability | Implementation | Availability |
|---|---|---|---|
| F91 | Mark mail read after ingestion | [email](../backend/app/email) | Implemented |
| F121 | Confirm voice transcripts before use | [voicecheck](../backend/app/voicecheck) | Relevant project evidence / state |
| F151 | Shared-secret Telegram webhook | [telegram](../backend/app/telegram) | Secret must be configured |
| F181 | Prompt Telegram receipt and drop reporting | [telegram](../backend/app/telegram) | Configuration / external service |

## Drawing evidence

```mermaid
flowchart TB
    F03["Bundled drawing revisions"]:::drawings
    F08["Drawing comparison"]:::drawings
    F80["Cross-sheet revision checks"]:::drawings
    F102["Identify work reported<br/>before a change"]:::drawings
    F104["PDF-only drawing comparison"]:::drawings
    F107["Read drawing title-block<br/>photos"]:::drawings
    F114["Scope rework notices to the<br/>reporter"]:::drawings
    F155["Scope cross-sheet guest<br/>notices"]:::drawings
    F177["Identify the outdated<br/>related sheet"]:::drawings
    F03 -.-> F08
    F03 -.-> F80
    F08 -.-> F102
    F08 -.-> F104
    F80 -.-> F107
    F80 -.-> F114
    F102 -.-> F155
    F102 -.-> F177
    classDef drawings fill:#e8f5f0,stroke:#33836d,color:#163f35
    click F03 "https://github.com/TabanAziz/talona-aurora/tree/main/data/drawings" "Open implementation"
    click F08 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/drawings" "Open implementation"
    click F80 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/crosscheck" "Open implementation"
    click F102 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/rework" "Open implementation"
    click F104 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/pdfdiff" "Open implementation"
    click F107 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/titleblock" "Open implementation"
    click F114 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/rework" "Open implementation"
    click F155 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/crosscheck" "Open implementation"
    click F177 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/crosscheck" "Open implementation"
```

| Ref | Capability | Implementation | Availability |
|---|---|---|---|
| F03 | Bundled drawing revisions | [drawings](../data/drawings) | Implemented |
| F08 | Drawing comparison | [drawings](../backend/app/drawings) | Relevant project evidence / state |
| F80 | Cross-sheet revision checks | [crosscheck](../backend/app/crosscheck) | Relevant project evidence / state |
| F102 | Identify work reported before a change | [rework](../backend/app/rework) | Relevant project evidence / state |
| F104 | PDF-only drawing comparison | [pdfdiff](../backend/app/pdfdiff) | Relevant project evidence / state |
| F107 | Read drawing title-block photos | [titleblock](../backend/app/titleblock) | Configuration / external service |
| F114 | Scope rework notices to the reporter | [rework](../backend/app/rework) | Relevant project evidence / state |
| F155 | Scope cross-sheet guest notices | [crosscheck](../backend/app/crosscheck) | Relevant project evidence / state |
| F177 | Identify the outdated related sheet | [crosscheck](../backend/app/crosscheck) | Relevant project evidence / state |

## Interpretation, rules and project context · 1

```mermaid
flowchart TB
    F06["Structured fact extraction"]:::intelligence
    F07["Project record and waiting<br/>items"]:::intelligence
    F09["Outdated drawing and<br/>acknowledgement rules"]:::intelligence
    F10["Inspection sequence checks"]:::intelligence
    F12["Dependency-based schedule<br/>proposals"]:::intelligence
    F11["Delivery and equipment<br/>deviations"]:::intelligence
    F13["Apply reviewed decisions"]:::intelligence
    F52["Reconcile drawing<br/>confirmations"]:::intelligence
    F23["Source-backed crew<br/>questions"]:::intelligence
    F25["Rules from reviewed<br/>decisions"]:::intelligence
    F24["Typed site instructions"]:::intelligence
    F48["Background mailbox polling"]:::intelligence
    F06 -.-> F07
    F06 -.-> F09
    F07 -.-> F10
    F07 -.-> F12
    F09 -.-> F11
    F09 -.-> F13
    F10 -.-> F52
    F10 -.-> F23
    F12 -.-> F25
    F12 -.-> F24
    F11 -.-> F48
    classDef intelligence fill:#fff1df,stroke:#b77929,color:#553711
    click F06 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/extract" "Open implementation"
    click F07 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/record" "Open implementation"
    click F09 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/rules_drawings" "Open implementation"
    click F10 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/rules_sequence" "Open implementation"
    click F12 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/schedule" "Open implementation"
    click F11 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/rules_resources" "Open implementation"
    click F13 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/decisions" "Open implementation"
    click F52 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/rules_drawings" "Open implementation"
    click F23 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/qa" "Open implementation"
    click F25 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/learning" "Open implementation"
    click F24 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/command" "Open implementation"
    click F48 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/core" "Open implementation"
```

| Ref | Capability | Implementation | Availability |
|---|---|---|---|
| F06 | Structured fact extraction | [extract](../backend/app/extract) | Implemented |
| F07 | Project record and waiting items | [record](../backend/app/record) | Implemented |
| F09 | Outdated drawing and acknowledgement rules | [rules_drawings](../backend/app/rules_drawings) | Relevant project evidence / state |
| F10 | Inspection sequence checks | [rules_sequence](../backend/app/rules_sequence) | Relevant project evidence / state |
| F12 | Dependency-based schedule proposals | [schedule](../backend/app/schedule) | Relevant project evidence / state |
| F11 | Delivery and equipment deviations | [rules_resources](../backend/app/rules_resources) | Relevant project evidence / state |
| F13 | Apply reviewed decisions | [decisions](../backend/app/decisions) | Relevant project evidence / state |
| F52 | Reconcile drawing confirmations | [rules_drawings](../backend/app/rules_drawings) | Relevant project evidence / state |
| F23 | Source-backed crew questions | [qa](../backend/app/qa) | Relevant project evidence / state |
| F25 | Rules from reviewed decisions | [learning](../backend/app/learning) | Relevant project evidence / state |
| F24 | Typed site instructions | [command](../backend/app/command) | Relevant project evidence / state |
| F48 | Background mailbox polling | [core](../backend/app/core) | Configuration / external service |

## Interpretation, rules and project context · 2

```mermaid
flowchart TB
    F62["Unresolved-hold schedule<br/>impact"]:::intelligence
    F64["Learned resource-deviation<br/>tolerance"]:::intelligence
    F65["Site context over MCP"]:::intelligence
    F67["Task-level start checks"]:::intelligence
    F68["Readiness checks and crew<br/>briefings"]:::intelligence
    F69["Insights from the project<br/>record"]:::intelligence
    F71["Reuse standing-rule<br/>decisions"]:::intelligence
    F72["Refresh proposals after new<br/>evidence"]:::intelligence
    F74["Visible model failures"]:::intelligence
    F77["Bounded guest messaging"]:::intelligence
    F79["Follow up on unreported<br/>results"]:::intelligence
    F83["Scoped automatic-hold<br/>permissions"]:::intelligence
    F62 -.-> F64
    F62 -.-> F65
    F64 -.-> F67
    F64 -.-> F68
    F65 -.-> F69
    F65 -.-> F71
    F67 -.-> F72
    F67 -.-> F74
    F68 -.-> F77
    F68 -.-> F79
    F69 -.-> F83
    classDef intelligence fill:#fff1df,stroke:#b77929,color:#553711
    click F62 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/schedule" "Open implementation"
    click F64 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/rules_resources" "Open implementation"
    click F65 "https://github.com/TabanAziz/talona-aurora/tree/main/integrations/mcp" "Open implementation"
    click F67 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/gate" "Open implementation"
    click F68 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/readiness" "Open implementation"
    click F69 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/insights" "Open implementation"
    click F71 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/rules_sequence" "Open implementation"
    click F72 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/core" "Open implementation"
    click F74 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/qa" "Open implementation"
    click F77 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/guest" "Open implementation"
    click F79 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/followup" "Open implementation"
    click F83 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/autonomy" "Open implementation"
```

| Ref | Capability | Implementation | Availability |
|---|---|---|---|
| F62 | Unresolved-hold schedule impact | [schedule](../backend/app/schedule) | Relevant project evidence / state |
| F64 | Learned resource-deviation tolerance | [rules_resources](../backend/app/rules_resources) | Relevant project evidence / state |
| F65 | Site context over MCP | [mcp](../integrations/mcp) | Configuration / external service |
| F67 | Task-level start checks | [gate](../backend/app/gate) | Implemented |
| F68 | Readiness checks and crew briefings | [readiness](../backend/app/readiness) | Configuration / external service |
| F69 | Insights from the project record | [insights](../backend/app/insights) | Relevant project evidence / state |
| F71 | Reuse standing-rule decisions | [rules_sequence](../backend/app/rules_sequence) | Relevant project evidence / state |
| F72 | Refresh proposals after new evidence | [core](../backend/app/core) | Relevant project evidence / state |
| F74 | Visible model failures | [qa](../backend/app/qa) | Relevant project evidence / state |
| F77 | Bounded guest messaging | [guest](../backend/app/guest) | Configuration / external service |
| F79 | Follow up on unreported results | [followup](../backend/app/followup) | Relevant project evidence / state |
| F83 | Scoped automatic-hold permissions | [autonomy](../backend/app/autonomy) | Relevant project evidence / state |

## Interpretation, rules and project context · 3

```mermaid
flowchart TB
    F88["Preserve human inspection<br/>holds"]:::intelligence
    F90["Site-time decision messages"]:::intelligence
    F95["Clarify an unclear message"]:::intelligence
    F96["Remember clarified names"]:::intelligence
    F101["Daily report delivery"]:::intelligence
    F113["Scope follow-up recipients"]:::intelligence
    F143["Machine drawing receipt and<br/>confirmation"]:::intelligence
    F144["Structured machine<br/>observations"]:::intelligence
    F161["Occupied-unit machine<br/>checks"]:::intelligence
    F162["Delivery observations from<br/>a gate sensor"]:::intelligence
    F163["Machine section in the<br/>daily report"]:::intelligence
    F86["Explain unclear messages"]:::intelligence
    F88 -.-> F90
    F88 -.-> F95
    F90 -.-> F96
    F90 -.-> F101
    F95 -.-> F113
    F95 -.-> F143
    F96 -.-> F144
    F96 -.-> F161
    F101 -.-> F162
    F101 -.-> F163
    F113 -.-> F86
    classDef intelligence fill:#fff1df,stroke:#b77929,color:#553711
    click F88 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/rules_sequence" "Open implementation"
    click F90 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/decisions" "Open implementation"
    click F95 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/clarify" "Open implementation"
    click F96 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/names" "Open implementation"
    click F101 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/dailyreport" "Open implementation"
    click F113 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/followup" "Open implementation"
    click F143 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/machine" "Open implementation"
    click F144 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/machinereport" "Open implementation"
    click F161 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/gate" "Open implementation"
    click F162 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/machinereport" "Open implementation"
    click F163 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/dailyreport" "Open implementation"
    click F86 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/record" "Open implementation"
```

| Ref | Capability | Implementation | Availability |
|---|---|---|---|
| F88 | Preserve human inspection holds | [rules_sequence](../backend/app/rules_sequence) | Relevant project evidence / state |
| F90 | Site-time decision messages | [decisions](../backend/app/decisions) | Relevant project evidence / state |
| F95 | Clarify an unclear message | [clarify](../backend/app/clarify) | Relevant project evidence / state |
| F96 | Remember clarified names | [names](../backend/app/names) | Relevant project evidence / state |
| F101 | Daily report delivery | [dailyreport](../backend/app/dailyreport) | Configuration / external service |
| F113 | Scope follow-up recipients | [followup](../backend/app/followup) | Relevant project evidence / state |
| F143 | Machine drawing receipt and confirmation | [machine](../backend/app/machine) | Simulation / structured observation |
| F144 | Structured machine observations | [machinereport](../backend/app/machinereport) | Simulation / structured observation |
| F161 | Occupied-unit machine checks | [gate](../backend/app/gate) | Relevant project evidence / state |
| F162 | Delivery observations from a gate sensor | [machinereport](../backend/app/machinereport) | Simulation / structured observation |
| F163 | Machine section in the daily report | [dailyreport](../backend/app/dailyreport) | Relevant project evidence / state |
| F86 | Explain unclear messages | [record](../backend/app/record) | Relevant project evidence / state |

## Interpretation, rules and project context · 4

```mermaid
flowchart TB
    F112["Mailbox status and errors"]:::intelligence
    F133["Count standing-rule<br/>applications once"]:::intelligence
    F152["Named inspection sign-off<br/>replies"]:::intelligence
    F153["Clarification reply<br/>identity"]:::intelligence
    F154["Per-day crew briefing<br/>deduplication"]:::intelligence
    F173["Record-day automatic-hold<br/>counts"]:::intelligence
    F178["Bound clarified-name<br/>retries"]:::intelligence
    F179["Validate start-check asker<br/>names"]:::intelligence
    F112 -.-> F133
    F112 -.-> F152
    F133 -.-> F153
    F133 -.-> F154
    F152 -.-> F173
    F152 -.-> F178
    F153 -.-> F179
    classDef intelligence fill:#fff1df,stroke:#b77929,color:#553711
    click F112 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/core" "Open implementation"
    click F133 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/insights" "Open implementation"
    click F152 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/followup" "Open implementation"
    click F153 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/clarify" "Open implementation"
    click F154 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/readiness" "Open implementation"
    click F173 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/autonomy" "Open implementation"
    click F178 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/names" "Open implementation"
    click F179 "https://github.com/TabanAziz/talona-aurora/tree/main/backend/app/gate" "Open implementation"
```

| Ref | Capability | Implementation | Availability |
|---|---|---|---|
| F112 | Mailbox status and errors | [core](../backend/app/core) | Relevant project evidence / state |
| F133 | Count standing-rule applications once | [insights](../backend/app/insights) | Relevant project evidence / state |
| F152 | Named inspection sign-off replies | [followup](../backend/app/followup) | Relevant project evidence / state |
| F153 | Clarification reply identity | [clarify](../backend/app/clarify) | Relevant project evidence / state |
| F154 | Per-day crew briefing deduplication | [readiness](../backend/app/readiness) | Configuration / external service |
| F173 | Record-day automatic-hold counts | [autonomy](../backend/app/autonomy) | Relevant project evidence / state |
| F178 | Bound clarified-name retries | [names](../backend/app/names) | Relevant project evidence / state |
| F179 | Validate start-check asker names | [gate](../backend/app/gate) | Relevant project evidence / state |

## Product views and interaction · 1

```mermaid
flowchart TB
    F14["Project overview"]:::interface
    F15["Issue details and evidence"]:::interface
    F16["Drawing comparison page"]:::interface
    F17["Work schedule"]:::interface
    F31["Project conversations"]:::interface
    F32["Responsive layout and dark<br/>appearance"]:::interface
    F46["3D view of the drawing<br/>comparison"]:::interface
    F63["Proof of notice"]:::interface
    F70["Rules and recorded decision<br/>insights"]:::interface
    F75["Printed drawing QR and<br/>status page"]:::interface
    F76["Project timeline and<br/>decision counts"]:::interface
    F81["Simulated layout robot"]:::interface
    F14 -.-> F15
    F14 -.-> F16
    F15 -.-> F17
    F15 -.-> F31
    F16 -.-> F32
    F16 -.-> F46
    F17 -.-> F63
    F17 -.-> F70
    F31 -.-> F75
    F31 -.-> F76
    F32 -.-> F81
    classDef interface fill:#f0eefb,stroke:#7763b1,color:#32244f
    click F14 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/overview" "Open implementation"
    click F15 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/flag" "Open implementation"
    click F16 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/compare" "Open implementation"
    click F17 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/plan" "Open implementation"
    click F31 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/crew" "Open implementation"
    click F32 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/styles" "Open implementation"
    click F46 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/compare3d" "Open implementation"
    click F63 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/notice" "Open implementation"
    click F70 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/learned" "Open implementation"
    click F75 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/sheet" "Open implementation"
    click F76 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/timelapse" "Open implementation"
    click F81 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/robot" "Open implementation"
```

| Ref | Capability | Implementation | Availability |
|---|---|---|---|
| F14 | Project overview | [overview](../frontend/src/pages/overview) | Implemented |
| F15 | Issue details and evidence | [flag](../frontend/src/pages/flag) | Implemented |
| F16 | Drawing comparison page | [compare](../frontend/src/pages/compare) | Relevant project evidence / state |
| F17 | Work schedule | [plan](../frontend/src/pages/plan) | Implemented |
| F31 | Project conversations | [crew](../frontend/src/pages/crew) | Implemented |
| F32 | Responsive layout and dark appearance | [styles](../frontend/src/styles) | Implemented |
| F46 | 3D view of the drawing comparison | [compare3d](../frontend/src/pages/compare3d) | Relevant project evidence / state |
| F63 | Proof of notice | [notice](../frontend/src/pages/notice) | Relevant project evidence / state |
| F70 | Rules and recorded decision insights | [learned](../frontend/src/pages/learned) | Relevant project evidence / state |
| F75 | Printed drawing QR and status page | [sheet](../frontend/src/pages/sheet) | Direct route; navigation depends on comparison |
| F76 | Project timeline and decision counts | [timelapse](../frontend/src/pages/timelapse) | Implemented |
| F81 | Simulated layout robot | [robot](../frontend/src/pages/robot) | Simulation / structured observation |

## Product views and interaction · 2

```mermaid
flowchart TB
    F84["Grant and revoke automatic<br/>holds"]:::interface
    F94["Notification delivery<br/>evidence"]:::interface
    F99["Recorded quality-check<br/>results"]:::interface
    F100["Daily report from the<br/>record"]:::interface
    F103["Rework evidence and cost<br/>assumptions"]:::interface
    F108["Reported actuals beside<br/>planned work"]:::interface
    F135["Floor-stack comparisons and<br/>callouts"]:::interface
    F136["Automatic-decision counter"]:::interface
    F137["Issue-to-notice link and<br/>print view"]:::interface
    F138["Plain-language schedule<br/>impact"]:::interface
    F140["Affected crews and machines"]:::interface
    F141["Robot waits and works<br/>around blocks"]:::interface
    F84 -.-> F94
    F84 -.-> F99
    F94 -.-> F100
    F94 -.-> F103
    F99 -.-> F108
    F99 -.-> F135
    F100 -.-> F136
    F100 -.-> F137
    F103 -.-> F138
    F103 -.-> F140
    F108 -.-> F141
    classDef interface fill:#f0eefb,stroke:#7763b1,color:#32244f
    click F84 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/autonomy" "Open implementation"
    click F94 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/notice" "Open implementation"
    click F99 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/evaluation" "Open implementation"
    click F100 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/daily" "Open implementation"
    click F103 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/rework" "Open implementation"
    click F108 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/plan" "Open implementation"
    click F135 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/compare3d" "Open implementation"
    click F136 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/overview" "Open implementation"
    click F137 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/notice" "Open implementation"
    click F138 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/plan" "Open implementation"
    click F140 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/flag" "Open implementation"
    click F141 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/robot" "Open implementation"
```

| Ref | Capability | Implementation | Availability |
|---|---|---|---|
| F84 | Grant and revoke automatic holds | [autonomy](../frontend/src/pages/autonomy) | Relevant project evidence / state |
| F94 | Notification delivery evidence | [notice](../frontend/src/pages/notice) | Relevant project evidence / state |
| F99 | Recorded quality-check results | [evaluation](../frontend/src/pages/evaluation) | Implemented |
| F100 | Daily report from the record | [daily](../frontend/src/pages/daily) | Implemented |
| F103 | Rework evidence and cost assumptions | [rework](../frontend/src/pages/rework) | Relevant project evidence / state |
| F108 | Reported actuals beside planned work | [plan](../frontend/src/pages/plan) | Relevant project evidence / state |
| F135 | Floor-stack comparisons and callouts | [compare3d](../frontend/src/pages/compare3d) | Relevant project evidence / state |
| F136 | Automatic-decision counter | [overview](../frontend/src/pages/overview) | Relevant project evidence / state |
| F137 | Issue-to-notice link and print view | [notice](../frontend/src/pages/notice) | Relevant project evidence / state |
| F138 | Plain-language schedule impact | [plan](../frontend/src/pages/plan) | Relevant project evidence / state |
| F140 | Affected crews and machines | [flag](../frontend/src/pages/flag) | Relevant project evidence / state |
| F141 | Robot waits and works around blocks | [robot](../frontend/src/pages/robot) | Simulation / structured observation |

## Product views and interaction · 3

```mermaid
flowchart TB
    F149["Equipment status and start<br/>checks"]:::interface
    F150["Simulated survey drone"]:::interface
    F157["Building and live site view"]:::interface
    F159["Prepared baseline day<br/>playback"]:::interface
    F160["Room-level start-check<br/>controls"]:::interface
    F164["Building preview on the<br/>overview"]:::interface
    F165["Record-driven site actors"]:::interface
    F145["Daily report date and<br/>waiting scope"]:::interface
    F146["Revision identity and QR<br/>contrast"]:::interface
    F170["Conversation selection and<br/>answer focus"]:::interface
    F171["Notice outcome and crew<br/>counts"]:::interface
    F174["Revision status from<br/>comparison and label"]:::interface
    F149 -.-> F150
    F149 -.-> F157
    F150 -.-> F159
    F150 -.-> F160
    F157 -.-> F164
    F157 -.-> F165
    F159 -.-> F145
    F159 -.-> F146
    F160 -.-> F170
    F160 -.-> F171
    F164 -.-> F174
    classDef interface fill:#f0eefb,stroke:#7763b1,color:#32244f
    click F149 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/machines" "Open implementation"
    click F150 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/drone" "Open implementation"
    click F157 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/site" "Open implementation"
    click F159 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/siteplay" "Open implementation"
    click F160 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/siteask" "Open implementation"
    click F164 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/overview" "Open implementation"
    click F165 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/sitescene" "Open implementation"
    click F145 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/daily" "Open implementation"
    click F146 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/sheet" "Open implementation"
    click F170 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/crew" "Open implementation"
    click F171 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/notice" "Open implementation"
    click F174 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/sheet" "Open implementation"
```

| Ref | Capability | Implementation | Availability |
|---|---|---|---|
| F149 | Equipment status and start checks | [machines](../frontend/src/pages/machines) | Implemented |
| F150 | Simulated survey drone | [drone](../frontend/src/pages/drone) | Simulation / structured observation |
| F157 | Building and live site view | [site](../frontend/src/pages/site) | Implemented |
| F159 | Prepared baseline day playback | [siteplay](../frontend/src/pages/siteplay) | Bundled baseline only |
| F160 | Room-level start-check controls | [siteask](../frontend/src/pages/siteask) | Relevant project evidence / state |
| F164 | Building preview on the overview | [overview](../frontend/src/pages/overview) | Relevant project evidence / state |
| F165 | Record-driven site actors | [sitescene](../frontend/src/pages/sitescene) | Simulation / structured observation |
| F145 | Daily report date and waiting scope | [daily](../frontend/src/pages/daily) | Relevant project evidence / state |
| F146 | Revision identity and QR contrast | [sheet](../frontend/src/pages/sheet) | Implemented |
| F170 | Conversation selection and answer focus | [crew](../frontend/src/pages/crew) | Relevant project evidence / state |
| F171 | Notice outcome and crew counts | [notice](../frontend/src/pages/notice) | Relevant project evidence / state |
| F174 | Revision status from comparison and label | [sheet](../frontend/src/pages/sheet) | Relevant project evidence / state |

## Product views and interaction · 4

```mermaid
flowchart TB
    F180["Timeline dates and count<br/>labels"]:::interface
    F183["QR host from build URL or<br/>page origin"]:::interface
    F184["Label and status actions on<br/>sheet pages"]:::interface
    F188["Layout robot in the Plans<br/>menu"]:::interface
    F180 -.-> F183
    F180 -.-> F184
    F183 -.-> F188
    classDef interface fill:#f0eefb,stroke:#7763b1,color:#32244f
    click F180 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/timelapse" "Open implementation"
    click F183 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/sheet/labelUrl.js" "Open implementation"
    click F184 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/pages/sheet" "Open implementation"
    click F188 "https://github.com/TabanAziz/talona-aurora/tree/main/frontend/src/components" "Open implementation"
```

| Ref | Capability | Implementation | Availability |
|---|---|---|---|
| F180 | Timeline dates and count labels | [timelapse](../frontend/src/pages/timelapse) | Relevant project evidence / state |
| F183 | QR host from build URL or page origin | [labelUrl.js](../frontend/src/pages/sheet/labelUrl.js) | Build-time URL or page origin |
| F184 | Label and status actions on sheet pages | [sheet](../frontend/src/pages/sheet) | Relevant project evidence / state |
| F188 | Layout robot in the Plans menu | [components](../frontend/src/components) | Implemented |

## Corrections to the earlier atlas

- The standalone chat-export audit is not part of this repository and is not shown as an available product feature.
- QR labels still exist. Their host comes from `VITE_PUBLIC_URL` or the page origin, not from a shipped deployment helper. The current label omits workspace identity, so a phone must be on the intended project in a multi-project setup.
- Telegram shared-secret validation only applies when a secret is configured. A module existing does not establish a secured live connection.
- The layout robot and survey drone are simulations. The hotel drone example refuses clearance when it cannot identify a matching survey task.
- Prepared-day playback belongs to the bundled baseline. Imported hotel workspaces use incoming messages and currently have no prepared next event.
- The current interface says **Messages**, **Saved rules**, **Quality checks** and **Automation** in navigation; some page headings retain older names.
- Project creation, reviewed imports, channel assignment, a drawing register, visible processing stages and per-floor views are included here even though the older atlas did not capture the newer project flow.
- Adaption is represented as synthetic-data preparation. It is not a required live inference service or evidence of fine-tuning.

Each capability links to the current product implementation so the map can be checked as the application evolves.
