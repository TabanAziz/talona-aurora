# Demo walkthrough

The demonstration follows one problem through several channels: a drawing changes, a crew still intends to use the old revision, and a delivery moves. The point is to show how each update reaches the project record and changes the next decision.

## The project and its source files

Danube Forum Hotel is a fictional Vienna construction project with 120 guest rooms over six upper floors and a ground floor for reception, restaurant and conference facilities. Each guest floor has 20 rooms: 101 to 120, 201 to 220, continuing through 601 to 620. The footprint is 60 by 24 metres. These dimensions are demonstration assumptions, not a construction-approved design.

The example files are in [demo-data](demo-data/):

| File | Purpose | When to use it |
|---|---|---|
| [Aurora_Project_EN.json](demo-data/Aurora_Project_EN.json) | Project metadata, room and team identifiers, tasks, delivery resources, dependencies, machines and drawing geometry | Initial import |
| [H-100_Rev_A.pdf](demo-data/H-100_Rev_A.pdf) | Drawing of the complete building | Initial import |
| [H-101_Rev_A.pdf](demo-data/H-101_Rev_A.pdf) | First-floor drawing, revision A | Initial import |
| [H-101_Rev_B.pdf](demo-data/H-101_Rev_B.pdf) | The revised first-floor drawing | Later revision email |
| [H-101_Rev_B.json](demo-data/H-101_Rev_B.json) | Geometry for that same revision B | Attach to the revision email with its PDF |
| [Construction_Schedule_EN.csv](demo-data/Construction_Schedule_EN.csv) | Readable export of the initial task schedule | Reference; not required alongside the project JSON |

Upload the first three files together. Keep revision B for the later change. The imported JSON provides the initial teams and delivery dates; these are not inferred from the floor-plan PDFs. The model reviews a structured import without rewriting its supplied geometry, dates or tasks. A description-only setup can propose assumptions for review, but the file-based route is the repeatable example used here.

There are 123 tracked work areas: 120 guest rooms and three ground-floor areas. The geometry also names circulation and service spaces, so the viewer's room-and-area label count can be higher. The 15 team entries comprise six fit-out teams, six inspection teams, site logistics, a crane team and the layout robot. The survey drone is registered as equipment separately.

## The initial programme

There are 604 tasks: five steps for each guest room and four shared delivery or roof-related tasks. A room's sequence is wall-position layout, internal wall framing, electrical and plumbing installation, inspection, and wall closure. Dependencies record what must come first. A planned inspection appointment does not itself record a passed inspection.

| Resource or activity | Initial booking, Vienna local time |
|---|---|
| Wall panel delivery | Three trucks, Monday 16 November 2026 at 07:00 |
| Electrical and plumbing materials | One truck, Tuesday 17 November at 07:00 |
| Mobile crane | Monday 16 November, 08:00 to 12:00 |
| Roof weather protection | Tuesday 17 November, 08:00 to 16:00 |
| Project handover | Friday 18 December at 16:00 |

For room 101, the initial layout task is Monday 08:00 to 08:15, followed by wall framing from 08:15 to 10:15. Services are booked for Tuesday 08:00 to 10:00, inspection for 10:00 to 10:30, and closure for 10:30 to 12:30. These are synthetic scheduling inputs. The Telegram example below reports a different intended start time, which is retained as a separate source.

The imported timestamps include `+01:00`. Some schedule controls explicitly display UTC, which is one hour earlier than Vienna for these November dates. The handover date shown at the top of Schedule is the project's target, not today's date.

## Live-service configuration

The Docker start command in the [README](../README.md#start-locally) opens a baseline with simulated external services. To create this hotel through model-assisted review, or interpret newly written messages, configure a live model in `.env` before starting the process. Never put real credentials in these example files.

| Service | Required configuration for the live path |
|---|---|
| Model interpretation and setup | `MISTRAL_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, and `USE_MOCK_LLM=false`. Project setup selects `PROJECT_SETUP_MODEL` when provided, otherwise `LLM_MODEL`, and currently requires a DeepSeek model identifier. |
| Email | `EMAIL_ADDRESS`, `EMAIL_APP_PASSWORD`, IMAP/SMTP hosts, and `USE_MOCK_EMAIL_API=false` |
| Telegram | `TELEGRAM_BOT_TOKEN`, the intended `TELEGRAM_CHAT_ID`, and `USE_MOCK_TELEGRAM_API=false` |
| Voice transcription | `ELEVENLABS_API_KEY` and `USE_MOCK_VOICE_API=false` |

Changing environment variables requires restarting the process or recreating the container. Keep `LLM_RECORD` off when handling material that should not be saved into replay fixtures.

Incoming Telegram updates need either a webhook to the reachable `/api/channels/telegram/webhook` endpoint or a deliberately configured polling process. For a webhook, configure a matching `TELEGRAM_WEBHOOK_SECRET` in the app and Telegram registration. For local polling, use `TELEGRAM_POLL_ENABLED=true` after assigning the group to the intended project. The same bot should not have competing receiving processes.

During project review, the checkbox labelled **Use the configured demo Telegram group and email inbox for this project** explicitly moves the shared demonstration accounts to the new project. Select it only for the project that should receive the next messages. This is account routing; it does not create a new inbox or bot for every project. Confirm channel assignment succeeds before sending the examples.

The backend's `/health` response shows simulated-service flags. The workspace connection and channel-target endpoints report configuration and project routing; a configured credential alone does not establish that an external message was received.

## 1. Create the hotel

Open **Aurora projects**, then **New project**. Use this name:

Danube Forum Hotel

Use this description:

> A fictional hotel construction project in Vienna with 120 guest rooms on six upper floors and reception, restaurant and conference facilities on the ground floor. Use the supplied geometry and programme, preserve the room and drawing identifiers, and present the project in English. The layout robot marks wall positions from the current drawing. The survey drone is simulated and requires a matching scheduled task before starting.

Upload `Aurora_Project_EN.json`, `H-100_Rev_A.pdf` and `H-101_Rev_A.pdf`. Prepare the draft, review its **Project**, **Programme** and **Drawings** sections, and inspect the assumptions. Select the channel checkbox for a live demonstration, acknowledge the review and choose **Create project**, then **Open project**.

Expected result: the project has its own room list, teams, initial schedule and two drawing sheets. Importing a planned task does not report that its work has started or finished.

## 2. Inspect a floor

Open **Plans → Drawings & revisions**, select **H-100**, and choose **3D**. Use **Floor** to select **Level 1**. Rotate, zoom or open **Full screen**. **Building** and **Explore floors** give different presentations of the supplied storeys. The PDF view remains available for checking the source drawing.

Explain that the same identifier, such as room 101, links the model to its tasks, crew messages and issues. The 3D view is a way into the project record, not a separate source of surveyed truth.

## 3. Send the new drawing

Send an email from a separate account to the configured project mailbox. Attach both `H-101_Rev_B.pdf` and `H-101_Rev_B.json`.

Subject:

Danube Forum Hotel: H-101 revision B

Body:

> H-101 revision B replaces revision A for rooms 101 to 120. The bathroom partition in room 101 moves 300 mm east. Use revision B for all first-floor layout and construction work. Please notify Fit-out team 1 and layout-robot-1 and request confirmation.

Wait until the incoming message and processing result are visible. Open the recorded drawing change from **Overview** or **Messages**. In **Drawings & revisions**, select **H-101** and look under **Revision changes** for **Compare Rev A with Rev B**.

Expected result: before, after and overlay views show the moved wall; a 3D comparison is available when both revisions have geometry. **Proof of notice** shows the notification and confirmation record. A sent message, a received message and an explicit acknowledgement are different events.

## 4. Send the crew voice note

In the configured Telegram group, send this spoken message:

> This is Fit-out team 1. We are starting the internal wall frames in room 101 on Monday, 16 November at nine, using H-101 revision A.

Confirm Aurora's transcription when asked. This confirms what was said; it is not the separate acknowledgement that the crew has adopted revision B.

Expected result: Aurora links the announced work to room 101 and the superseded drawing. Open the issue to inspect the voice message and revision evidence. The site manager can choose **Hold work** and record the reason. The resulting decision and crew notice remain visible in the app.

## 5. Report the delivery delay

Send this update through the configured demonstration channel:

> The wall panel delivery booked for Monday, 16 November will not arrive on Monday. All three trucks will now arrive on Wednesday, 18 November. Please update the proposed schedule.

Open **Schedule → Work schedule**. Inspect **Reported schedule warnings** and the proposal showing downstream impact. Review the affected tasks, old and new dates and any handover effect before choosing the proposal's acceptance action.

Expected result: the delayed arrival is recorded against the original three-truck booking. A dependency-based proposal is calculated. Dates change after acceptance. The impact depends on the task graph and working-day rules; it is not a blanket two-day shift of every task.

## 6. Show the machine boundary

Open **Plans → Layout robot**. Load the current revision and inspect its room-level start checks before running the simulation. In this dataset, the task name **Frame partitions** on the robot's layout task means marking wall positions. Human assembly of internal wall frames is a separate task. A decision on one task is evaluated in its scope rather than automatically stopping every activity in the building.

The simulation records requests and results, uses the current drawing and can wait or work around blocked work as its checks allow. It does not establish that a physical robot built a wall.

Open **Plans → Survey drone** to demonstrate the same permission boundary. The initial hotel programme does not contain an unambiguous survey task for the room used in the recorded scene. The start check refuses clearance, and the simulated drone remains grounded for review. Present that outcome as a refusal, not a completed survey.

## Finding the other views

Open a dropdown with the small arrow beside the main navigation tab.

| View | Navigation |
|---|---|
| Daily report and print action | **Overview → Daily report** |
| Event and decision history | **Overview → Project timeline** |
| Rules derived from decisions | **Overview → Saved rules** |
| Recorded evaluation results | **Overview → Quality checks** |
| Proposed actions from a typed instruction | **Messages → Give an instruction** |
| Automatic-hold permissions | **Schedule → Automation**; the page heading is **Autonomy** |
| Equipment and recorded start checks | **Plans → Equipment** |
| Room-level start check | **Plans → Building & live site**, select a room, then **May this start?** |
| Weekly schedule chart | **Schedule → Work schedule**, expand **Weekly timeline** |

The **Play the day** control on the site view drives the bundled baseline scenario. Imported workspaces currently return no prepared next event, so use incoming messages for this hotel rather than expecting that control to replay the hotel story.

## Printed-plan QR labels

After a drawing comparison exists, open it and find **Revisions of this sheet → Label / Status**. A label can be printed and scanned with a normal phone camera. Its status page checks the named revision against the current project record.

Before a comparison exists, the current drawing register has no label button. Open `/sheet/H-101/A/label` on the app's own host to reach the label directly. `/sheet/H-101/A` opens the corresponding status page. Once revision B has been registered, revision A should be marked **Superseded**.

The QR address uses `VITE_PUBLIC_URL` at frontend build time when provided, otherwise the page origin. A phone needs a reachable host, not the laptop's `localhost`. Printed links currently identify the sheet and revision without embedding a workspace ID; check that the phone is viewing the intended project before presenting this in a multi-project installation.

## What to say about the demonstration

The hotel, dates, quantities and crew role are synthetic. The recorded hotel run used real email and Telegram transport. A fresh installation uses simulated adapters until they are configured. The robot and drone are simulated throughout. Adaption-generated history belongs to the separate baseline dataset and evaluation work; it is not evidence of real hotel-site activity.

The result being demonstrated is a traceable coordination workflow: source received, interpretation recorded, conflict identified, proposal reviewed, decision communicated. It does not demonstrate a certified design, a passed physical inspection or measured production savings.
