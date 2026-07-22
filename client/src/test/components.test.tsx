import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ApplicationShell, ScientificNameDisplay } from "../components";
import { orchid } from "./fixtures";

describe("accessible reusable components",()=>{
  it("renders semantic navigation, landmarks, skip link, and planned routes",()=>{render(<ApplicationShell onSignOut={vi.fn()}><h1>View</h1></ApplicationShell>);expect(screen.getByRole("navigation",{name:/primary/i})).toBeInTheDocument();expect(screen.getByRole("main")).toHaveAttribute("tabindex","-1");expect(screen.getByText("Skip to main content")).toHaveAttribute("href","#main-content");expect(screen.getByRole("link",{name:/reports/i})).toHaveAttribute("href","/conservatory/reports");});
  it("renders uncertainty with text rather than color alone",()=>{render(<ScientificNameDisplay plant={{...orchid,uncertainIdentification:true}}/>);expect(screen.getByText("Identification uncertain")).toBeVisible();expect(screen.getByText(/Accepted-name and synonym status/)).toBeVisible();});
  it("supports keyboard navigation through links",async()=>{render(<ApplicationShell onSignOut={vi.fn()}><h1>View</h1></ApplicationShell>);await userEvent.tab();expect(screen.getByText("Skip to main content")).toHaveFocus();});
});
