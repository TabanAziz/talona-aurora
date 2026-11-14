"""The written scenario for Maple Court: who says what, when, through which channel.

Plain data, no logic. generate.py turns it into events and source files. Eight events are the demo events
(ids e01 to e08, identical to mocks/scenario.json), and the two voice notes among them are each followed by their
sender's Confirm (e02-confirm, e06-confirm); the rest are routine traffic, a few more real problems,
two redeliveries and one message that arrives days after it was written. Nothing here says which is which:
the expected answers live in /eval.
"""

THREAD = "Maple Court site"

PEOPLE = {
    "Marco Ruiz": "Framing foreman",
    "Hannah Kowalski": "Electrical foreman",
    "Dmitri Volkov": "Concrete foreman",
    "Sam Okafor": "Site labor foreman",
    "Jonas Meyer": "Roofing foreman",
    "Priya Shah": "Drywall foreman",
    "Lena Ortiz": "Crane operator",
    "Dana Whitfield": "Architect",
    "Ridgeline Concrete dispatch": "Supplier",
    "Plumbing inspector": "Inspector",
    "Superintendent": "Superintendent",
    "Schedule update": None,
}

EMAIL_ADDRESSES = {
    "Dana Whitfield": "dana.whitfield@whitfield-architects.example",
    "Ridgeline Concrete dispatch": "dispatch@ridgeline-concrete.example",
    "Plumbing inspector": "plumbing@city-building-dept.example",
    "Hannah Kowalski": "hannah.kowalski@maplecourt-electrical.example",
}

# Fixed ids for the demo events. received_at is given as seconds after sent_at.
DEMO = {
    "e01": ("11-10 09:12", 20), "e02": ("11-12 16:05", 4), "e03": ("11-12 16:40", 30), "e04": ("11-12 17:02", 3),
    "e05": ("11-12 17:30", 0), "e06": ("11-13 06:40", 3), "e07": ("11-13 07:15", 2), "e08": ("11-13 07:20", 2),
    "e02-confirm": ("11-12 16:06", 2), "e06-confirm": ("11-13 06:41", 2),
    "e90": ("11-10 07:50", 2), "e91": ("11-10 08:20", 2),
}

# Each entry: (id or None, "MM-DD HH:MM", channel, sender, subject, text, options)
# options: audio=True (voice note, text empty, spoken text in `say`), say, pdf (attachment name),
# pdf_url, redelivery=seconds after the first delivery, received=("MM-DD HH:MM") for a late arrival,
# confirms=<id> for the sender's Confirm under Aurora's read-back of that voice note.
EVENTS = [
    # Week 45, history
    (None, "11-03 15:05", "schedule", "Schedule update", None, "Unit 1D rough plumbing inspection passed.", {}),
    (None, "11-04 07:20", "telegram", "Marco Ruiz", None,
     "Level two exterior walls are up. Starting the interior partitions on 2A and 2B next.", {}),
    (None, "11-04 08:00", "schedule", "Schedule update", None, "Weekly schedule issued.", {}),
    (None, "11-04 11:10", "schedule", "Schedule update", None, "Unit 1E rough plumbing inspection passed.", {}),
    (None, "11-05 07:05", "telegram", "Jonas Meyer", None,
     "Roof trusses are delivered and stacked on the south side. The count matches the packing list.", {}),
    (None, "11-05 08:15", "telegram", "Priya Shah", None, "",
     {"audio": True, "say": "Drywall crew is four people today, two of us are at the other site until noon."}),
    (None, "11-05 13:30", "email", "Ridgeline Concrete dispatch", "Podium topping pour booked",
     "Booking confirmed for the podium topping pour. 3 trucks, first truck on site at 6:00. "
     "Mix design as submitted.", {}),
    (None, "11-05 15:05", "schedule", "Schedule update", None, "Unit 1F rough plumbing inspection passed.", {}),
    (None, "11-05 15:20", "telegram", "Sam Okafor", None, "Curing blankets for the podium are on site, stored in the east bay.", {}),
    (None, "11-06 06:50", "telegram", "Marco Ruiz", None, "",
     {"audio": True, "say": "Morning. We are framing the level two corridor walls today, should be done by noon."}),
    (None, "11-06 14:00", "telegram", "Lena Ortiz", None,
     "The mobile crane is booked for the truss lift a week from today at seven. Please keep the access road clear.", {}),
    (None, "11-06 14:30", "telegram", "Superintendent", None, "Access road is clear, the gate crew opens at 6:30 on the day of the lift.", {}),
    (None, "11-06 16:10", "schedule", "Schedule update", None, "Unit 1G rough plumbing inspection passed.", {}),
    (None, "11-06 16:40", "telegram", "Priya Shah", None,
     "Board for level one is stacked in the 1E hallway. Hanging starts when each unit is signed off.", {}),
    # Week 46, before the first demo event
    (None, "11-09 07:15", "telegram", "Sam Okafor", None, "Site walk is done, fencing and signage are checked.", {}),
    (None, "11-09 08:00", "schedule", "Schedule update", None, "Weekly schedule issued.", {}),
    (None, "11-09 15:25", "schedule", "Schedule update", None, "Unit 1C rough plumbing inspection passed.", {}),
    (None, "11-09 17:05", "email", "Plumbing inspector", "Rough plumbing inspections 2A, 2B and 2D",
     "Rough plumbing: Unit 2A in three days at 13:00. Unit 2D in four days at 09:00. "
     "Unit 2B in seven days at 13:00.", {}),
    (None, "11-10 07:30", "email", "Dana Whitfield", "A-201 Rev B is current for level 3",
     "Reminder for all trades: A-201 Rev B is the current level 3 floor plan. Please lay out from Rev B.", {}),
    ("e90", "11-10 07:50", "telegram", "Hannah Kowalski", None,
     "We started rough electrical in 3A this morning.", {"historical_rework": True}),
    ("e91", "11-10 08:20", "email", "Dana Whitfield", "E-201 Rev B issued for 3A",
     "Attached E-201 Rev B. It replaces Rev A. The receptacle and panel layout in 3A has changed.",
     {"historical_rework": True, "pdf": "E-201-RevB.pdf"}),
    ("e01", "11-10 09:12", "email", "Dana Whitfield", "A-201 Rev C issued",
     "Attached A-201 Rev C. The partition between bedroom and living room in 3B shifts 300 mm north. "
     "Rev C replaces Rev B.", {"pdf": "A-201-RevC.pdf", "pdf_url": "/media/mock/a201-rev-c.svg"}),
    (None, "11-10 08:05", "telegram", "Dmitri Volkov", None, "Podium deck rebar was inspected this morning and passed.", {}),
    (None, "11-10 10:20", "telegram", "Hannah Kowalski", None, "Electrical crew is on level two today, home runs in 2C and 2D.", {}),
    (None, "11-10 13:00", "telegram", "Marco Ruiz", None, "Level two framing is about 80 percent done, I expect to finish tomorrow.", {}),
    (None, "11-10 15:10", "email", "Ridgeline Concrete dispatch", "Invoice 4471",
     "Invoice 4471 for last month's pours has been sent to accounting.", {}),
    (None, "11-10 16:15", "schedule", "Schedule update", None, "Unit 1H rough plumbing inspection passed.", {}),
    (None, "11-11 06:30", "telegram", "Dmitri Volkov", None,
     "Podium deck is cleaned and the rebar chairs are checked. We are ready for the pour.", {}),
    (None, "11-11 07:05", "telegram", "Jonas Meyer", None, "",
     {"audio": True, "say": "The truss lift is planned for the day after tomorrow at seven with the mobile crane. Crew of six, same as last week."}),
    (None, "11-11 12:10", "schedule", "Schedule update", None, "Unit 2C rough plumbing inspection passed.", {}),
    (None, "11-11 13:40", "telegram", "Sam Okafor", None, "Water and power for the curing heaters are connected on the podium.", {}),
    (None, "11-11 16:50", "email", "Dana Whitfield", "E-201 Rev B issued",
     "Attached E-201 Rev B. It replaces Rev A. The receptacle and panel layout in 3B is updated and clouded on the "
     "sheet. Please confirm with your crews.", {"pdf": "E-201-RevB.pdf"}),
    # Thursday 12 November
    (None, "11-12 06:45", "telegram", "Marco Ruiz", None, "Level two framing is finished. The crew goes up to level three tomorrow.", {}),
    (None, "11-12 09:00", "email", "Ridgeline Concrete dispatch", "Reminder: podium pour tomorrow",
     "Reminder: podium topping pour tomorrow, 3 trucks, first truck on site at 6:00.", {}),
    (None, "11-12 11:30", "telegram", "Priya Shah", None, "Board is on level two now, stacked in the 2B hallway.", {}),
    (None, "11-12 12:05", "telegram", "Hannah Kowalski", None, "",
     {"audio": True, "say": "We finish the home runs in 2E tomorrow, then after the weekend we move to 3B for the rough electrical."}),
    (None, "11-12 14:20", "telegram", "Dmitri Volkov", None, "Cylinder breaks from the last pour came back above spec.",
     {"redelivery": 90}),
    (None, "11-12 15:00", "telegram", "Superintendent", None,
     "Toolbox talk tomorrow at 6:30 at the gate, topic is fall protection. Everyone on site please.", {}),
    (None, "11-12 15:30", "telegram", "Jonas Meyer", None, "",
     {"audio": True, "say": "Roof sheathing follows the truss lift and takes two days, same crew."}),
    ("e02", "11-12 16:05", "telegram", "Marco Ruiz", None, "",
     {"audio": True, "say": "Starting the 3B partitions tomorrow at seven, per A-201 rev B."}),
    # Aurora reads a voice note back before it uses it; the sender confirms by typing the button label.
    ("e02-confirm", "11-12 16:06", "telegram", "Marco Ruiz", None, "Confirm", {"confirms": "e02"}),
    ("e03", "11-12 16:40", "email", "Ridgeline Concrete dispatch", "Friday pour: 4 trucks",
     "Confirming Friday's podium topping pour. We are sending 4 trucks instead of 3, the mix volume was revised. "
     "First truck on site 7:00.", {}),
    ("e04", "11-12 17:02", "telegram", "Lena Ortiz", None,
     "Heads up, the mobile crane gets to site Monday, not Friday. The transport permit slipped.", {}),
    ("e05", "11-12 17:30", "schedule", "Schedule update", None,
     "Unit 2A rough plumbing inspection moved from Thursday to Friday 14:00.", {}),
    (None, "11-12 17:45", "telegram", "Sam Okafor", None, "Curing protection is staged for tomorrow, blankets and heaters ready from nine.", {}),
    (None, "11-12 18:05", "telegram", "Marco Ruiz", None,
     "Heads up, two of my crew are out sick tomorrow. We will be four people on the 3B framing, not six.", {}),
    (None, "11-12 18:10", "email", "Dana Whitfield", "RFI 14 response",
     "RFI 14: the window flashing detail at the podium edge stays as drawn. No drawing change.", {"redelivery": 2700}),
    # Friday 13 November
    (None, "11-11 14:10", "email", "Hannah Kowalski", "2C rough electrical done",
     "2C rough electrical is finished, boxes and home runs are in. Photos are on the shared drive.",
     {"received": "11-13 05:50"}),
    (None, "11-13 06:15", "telegram", "Dmitri Volkov", None, "Pump is set up on the podium and the forms are checked. Ready for the trucks.", {}),
    ("e06", "11-13 06:40", "telegram", "Priya Shah", None, "",
     {"audio": True, "say": "Can we close the walls in 2A this morning?"}),
    ("e06-confirm", "11-13 06:41", "telegram", "Priya Shah", None, "Confirm", {"confirms": "e06"}),
    (None, "11-13 06:55", "telegram", "Hannah Kowalski", None, "Electrical crew is in 2E pulling wire today.", {}),
    ("e07", "11-13 07:15", "telegram", "Priya Shah", None, "What about 2B, can we close those walls?", {}),
    ("e08", "11-13 07:20", "telegram", "Priya Shah", None, "And 1C, can we close the walls there?", {}),
    (None, "11-13 07:35", "telegram", "Priya Shah", None, "",
     {"audio": True, "say": "2D, the plumbing inspector is coming at nine, so we wait on the walls there."}),
    (None, "11-13 08:10", "telegram", "Jonas Meyer", None, "Got it on the crane. The roof lift moves to the next working day and the trusses stay stacked.", {}),
    (None, "11-13 08:30", "telegram", "Hannah Kowalski", None, "",
     {"audio": True, "say": "On the next working day we start rough electrical in 3B. The wire is cut to length from E-201 rev A."}),
    (None, "11-13 10:40", "schedule", "Schedule update", None, "Unit 2D rough plumbing inspection passed.", {}),
    (None, "11-13 11:05", "telegram", "Priya Shah", None, "2D is signed off, we start closing the walls there after lunch.", {}),
    (None, "11-13 11:30", "email", "Ridgeline Concrete dispatch", "Podium pour complete",
     "The podium topping pour is complete. 4 trucks delivered, the last truck left site at 10:45.", {}),
    (None, "11-13 12:10", "telegram", "Dmitri Volkov", None, "Pour is done and finishing is under way. The curing crew can start at one.", {}),
    (None, "11-13 13:20", "telegram", "Sam Okafor", None, "Curing protection is on the podium.", {}),
]
