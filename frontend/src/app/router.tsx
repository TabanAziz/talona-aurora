import { Route, Routes } from "react-router-dom";
import { Layout } from "../components/Layout";
import { Empty } from "../components/States";
import { Overview } from "../pages/overview/Overview";
import { FlagDetail } from "../pages/flag/FlagDetail";
import { Compare } from "../pages/compare/Compare";
import { PlanView } from "../pages/plan/PlanView";
import { Crew } from "../pages/crew/Crew";
import { Notice } from "../pages/notice/Notice";
import { Rework } from "../pages/rework/Rework";
import { CommandPage } from "../pages/command/CommandPage";
import { Timelapse } from "../pages/timelapse/Timelapse";
import { Learned } from "../pages/learned/Learned";
import { SheetStatus } from "../pages/sheet/SheetStatus";
import { SheetLabel } from "../pages/sheet/SheetLabel";
import { Daily } from "../pages/daily/Daily";
import { Robot } from "../pages/robot/Robot";
import { Drone } from "../pages/drone/Drone";
import { Autonomy } from "../pages/autonomy/Autonomy";
import { Site } from "../pages/site/Site";
import { Machines } from "../pages/machines/Machines";
import { Evaluation } from "../pages/evaluation/Evaluation";
import { Drawings } from "../pages/drawings/Drawings";
import { Projects, NewProject } from "../pages/projects";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/projects" element={<Projects />} />
        <Route path="/projects/new" element={<NewProject />} />
        <Route path="/drawings" element={<Drawings />} />
        <Route path="/" element={<Overview />} />
        <Route path="/flags/:id" element={<FlagDetail />} />
        <Route path="/compare/:id" element={<Compare />} />
        <Route path="/notice/:id" element={<Notice />} />
        <Route path="/robot" element={<Robot />} />
        <Route path="/drone" element={<Drone />} />
        <Route path="/autonomy" element={<Autonomy />} />
        <Route path="/site" element={<Site />} />
        <Route path="/machines" element={<Machines />} />
        <Route path="/rework/:diffId/:unit" element={<Rework />} />
        <Route path="/sheet/:sheet/:revision" element={<SheetStatus />} />
        <Route path="/sheet/:sheet/:revision/label" element={<SheetLabel />} />
        <Route path="/plan" element={<PlanView />} />
        <Route path="/timelapse" element={<Timelapse />} />
        <Route path="/learned" element={<Learned />} />
        <Route path="/daily" element={<Daily />} />
        <Route path="/daily/:date" element={<Daily />} />
        <Route path="/evaluation" element={<Evaluation />} />
        <Route path="/crew" element={<Crew />} />
        <Route path="/instructions" element={<CommandPage />} />
        <Route path="*" element={<Empty>This page does not exist. Use the links at the top.</Empty>} />
      </Route>
    </Routes>
  );
}
