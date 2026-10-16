import { BrowserRouter, Route, Routes } from "react-router";
import { AppShell } from "@/components/app-shell";
import { HomePage } from "@/pages/home";
import { NotFoundPage } from "@/pages/not-found";

// One <Route> per page; pages live in src/pages/.
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
