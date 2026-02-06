-- Calyx Seed Data (Postgres)
-- Seeds: 1 org, 1 show, roles+shifts, 6 volunteers+assignments, 3 judges, 10 scores, 3 awards

-- 1) Organization
INSERT INTO organizations (id, name, created_at) VALUES
  ('org-001', 'Tri-State Orchid Society', NOW())
ON CONFLICT (id) DO NOTHING;

-- 2) Show
INSERT INTO shows (id, organization_id, name, start_date, location, judging_locked, public_volunteer_token, created_at) VALUES
  ('show-001', 'org-001', 'Spring Orchid Spectacular 2026', '2026-04-10', 'Grand Convention Center', false, 'public-demo-2026', NOW())
ON CONFLICT (id) DO NOTHING;

-- 3) Entries (needed for scoring)
INSERT INTO entries (id, show_id, exhibitor_name, plant_name, class_code, status, created_at) VALUES
  ('entry-001', 'show-001', 'Maria Lopez', 'Cattleya labiata', 'CAT-01', 'accepted', NOW()),
  ('entry-002', 'show-001', 'James Nguyen', 'Phalaenopsis equestris', 'PHAL-02', 'accepted', NOW()),
  ('entry-003', 'show-001', 'Susan Park', 'Dendrobium kingianum', 'DEN-03', 'accepted', NOW()),
  ('entry-004', 'show-001', 'Tom Baker', 'Oncidium Sharry Baby', 'ONC-04', 'accepted', NOW()),
  ('entry-005', 'show-001', 'Linda Chen', 'Vanda coerulea', 'VAN-05', 'accepted', NOW())
ON CONFLICT (id) DO NOTHING;

-- 4) Volunteer Roles
INSERT INTO volunteer_roles (id, show_id, name, description, default_shift_length, created_at) VALUES
  ('role-001', 'show-001', 'Admissions', 'Check tickets and guide visitors', 240, NOW()),
  ('role-002', 'show-001', 'Judging Assistant', 'Assist judges with scoring paperwork', 240, NOW()),
  ('role-003', 'show-001', 'Hospitality', 'Welcome guests, manage refreshments', 480, NOW())
ON CONFLICT (id) DO NOTHING;

-- 5) Volunteer Shifts (start_time/end_time are full datetimes)
INSERT INTO volunteer_shifts (id, show_id, role_id, start_time, end_time, capacity, created_at) VALUES
  ('shift-001', 'show-001', 'role-001', '2026-04-10 08:00:00', '2026-04-10 12:00:00', 3, NOW()),
  ('shift-002', 'show-001', 'role-001', '2026-04-10 12:00:00', '2026-04-10 16:00:00', 3, NOW()),
  ('shift-003', 'show-001', 'role-002', '2026-04-10 09:00:00', '2026-04-10 13:00:00', 2, NOW()),
  ('shift-004', 'show-001', 'role-003', '2026-04-10 08:00:00', '2026-04-10 16:00:00', 4, NOW()),
  ('shift-005', 'show-001', 'role-002', '2026-04-11 09:00:00', '2026-04-11 13:00:00', 2, NOW())
ON CONFLICT (id) DO NOTHING;

-- 6) Volunteers (6 total)
INSERT INTO volunteers (id, show_id, name, email, phone, opt_in_sms, notes, approved, created_at) VALUES
  ('vol-001', 'show-001', 'Alice Smith',    'alice@example.com',    '555-0101', false, NULL, true, NOW()),
  ('vol-002', 'show-001', 'Bob Johnson',    'bob@example.com',      '555-0102', true,  'Experienced volunteer', true, NOW()),
  ('vol-003', 'show-001', 'Carol Williams', 'carol@example.com',    '555-0103', false, NULL, true, NOW()),
  ('vol-004', 'show-001', 'Dave Brown',     'dave@example.com',     '555-0104', false, NULL, true, NOW()),
  ('vol-005', 'show-001', 'Eve Davis',      'eve@example.com',      '555-0105', false, NULL, false, NOW()),
  ('vol-006', 'show-001', 'Frank Miller',   'frank@example.com',    '555-0106', true,  NULL, true, NOW())
ON CONFLICT (id) DO NOTHING;

-- 7) Volunteer Assignments
INSERT INTO volunteer_assignments (id, show_id, volunteer_id, shift_id, status, created_at) VALUES
  ('asgn-001', 'show-001', 'vol-001', 'shift-001', 'confirmed', NOW()),
  ('asgn-002', 'show-001', 'vol-002', 'shift-001', 'confirmed', NOW()),
  ('asgn-003', 'show-001', 'vol-003', 'shift-002', 'assigned',  NOW()),
  ('asgn-004', 'show-001', 'vol-004', 'shift-003', 'checked_in', NOW()),
  ('asgn-005', 'show-001', 'vol-006', 'shift-003', 'confirmed', NOW()),
  ('asgn-006', 'show-001', 'vol-001', 'shift-004', 'assigned',  NOW()),
  ('asgn-007', 'show-001', 'vol-003', 'shift-004', 'assigned',  NOW()),
  ('asgn-008', 'show-001', 'vol-005', 'shift-002', 'assigned',  NOW())
ON CONFLICT (id) DO NOTHING;

-- 8) Judges (3, with roles)
INSERT INTO judges (id, show_id, name, email, role, created_at) VALUES
  ('judge-001', 'show-001', 'Dr. Patricia Fielding', 'p.fielding@orchids.org', 'head_judge', NOW()),
  ('judge-002', 'show-001', 'Robert Tanaka',         'r.tanaka@orchids.org',   'judge', NOW()),
  ('judge-003', 'show-001', 'Helen Marchetti',       'h.marchetti@orchids.org', 'judge', NOW())
ON CONFLICT (id) DO NOTHING;

-- 9) Score Submissions (10 total across 5 entries x 2-3 judges)
INSERT INTO score_submissions (id, show_id, entry_id, judge_id, total_points, points_breakdown, notes, created_at) VALUES
  ('score-001', 'show-001', 'entry-001', 'judge-001', 88, '{"form":28,"color":30,"size":30}', 'Excellent form', NOW()),
  ('score-002', 'show-001', 'entry-001', 'judge-002', 91, '{"form":30,"color":31,"size":30}', 'Outstanding color', NOW()),
  ('score-003', 'show-001', 'entry-002', 'judge-001', 82, '{"form":26,"color":28,"size":28}', 'Good specimen', NOW()),
  ('score-004', 'show-001', 'entry-002', 'judge-002', 79, '{"form":25,"color":27,"size":27}', NULL, NOW()),
  ('score-005', 'show-001', 'entry-002', 'judge-003', 85, '{"form":28,"color":29,"size":28}', 'Well-presented', NOW()),
  ('score-006', 'show-001', 'entry-003', 'judge-001', 75, '{"form":24,"color":25,"size":26}', NULL, NOW()),
  ('score-007', 'show-001', 'entry-003', 'judge-003', 78, '{"form":25,"color":27,"size":26}', 'Healthy roots', NOW()),
  ('score-008', 'show-001', 'entry-004', 'judge-002', 92, '{"form":31,"color":31,"size":30}', 'Best in class candidate', NOW()),
  ('score-009', 'show-001', 'entry-004', 'judge-003', 89, '{"form":29,"color":30,"size":30}', NULL, NOW()),
  ('score-010', 'show-001', 'entry-005', 'judge-001', 86, '{"form":28,"color":29,"size":29}', 'Vibrant blue', NOW())
ON CONFLICT (id) DO NOTHING;

-- 10) Awards (3, linked to entries)
INSERT INTO awards (id, entry_id, award_name, level, created_at) VALUES
  ('award-001', 'entry-004', 'Best Oncidium',    'Gold',   NOW()),
  ('award-002', 'entry-001', 'Best Cattleya',    'Silver', NOW()),
  ('award-003', 'entry-005', 'Judges Choice',    'Bronze', NOW())
ON CONFLICT (id) DO NOTHING;

-- 11) Feedback samples
INSERT INTO feedback (id, module, step, worked, confusion, suggestions, created_at) VALUES
  ('fb-001', 'volunteers', 'import', true, NULL, 'Excel import worked great', NOW()),
  ('fb-002', 'volunteers', 'signup', false, 'Could not find the signup link', 'Make the link more visible', NOW())
ON CONFLICT (id) DO NOTHING;

-- 12) Judging Event (expanded system)
INSERT INTO judging_events (id, show_id, name, judging_type, is_blind, status, created_at) VALUES
  ('jevt-001', 'show-001', 'Main Judging - Spring 2026', 'standard', false, 'published', NOW())
ON CONFLICT (id) DO NOTHING;

-- 13) Plant Categories
INSERT INTO plant_categories (id, judging_event_id, name, description, created_at) VALUES
  ('pcat-001', 'jevt-001', 'Cattleya Alliance', 'All Cattleya species and hybrids', NOW()),
  ('pcat-002', 'jevt-001', 'Phalaenopsis', 'Moth orchids, species and hybrids', NOW()),
  ('pcat-003', 'jevt-001', 'Dendrobium', 'Dendrobium species and hybrids', NOW())
ON CONFLICT (id) DO NOTHING;

-- 14) Judging Criteria (per category)
INSERT INTO judging_criteria (id, category_id, label, weight, max_points, created_at) VALUES
  ('crit-001', 'pcat-001', 'Form & Shape', 1.0, 35, NOW()),
  ('crit-002', 'pcat-001', 'Color & Pattern', 1.0, 35, NOW()),
  ('crit-003', 'pcat-001', 'Size & Substance', 1.0, 30, NOW()),
  ('crit-004', 'pcat-002', 'Form & Shape', 1.0, 35, NOW()),
  ('crit-005', 'pcat-002', 'Color & Pattern', 1.2, 35, NOW()),
  ('crit-006', 'pcat-002', 'Size & Substance', 0.8, 30, NOW()),
  ('crit-007', 'pcat-003', 'Form & Shape', 1.0, 35, NOW()),
  ('crit-008', 'pcat-003', 'Color & Pattern', 1.0, 35, NOW()),
  ('crit-009', 'pcat-003', 'Size & Substance', 1.0, 30, NOW())
ON CONFLICT (id) DO NOTHING;

-- 15) Exhibitors
INSERT INTO exhibitors (id, name, email, phone, created_at) VALUES
  ('exh-001', 'Maria Lopez',  'maria@orchids.com',  '555-2001', NOW()),
  ('exh-002', 'James Nguyen', 'james@orchids.com',  '555-2002', NOW()),
  ('exh-003', 'Susan Park',   'susan@orchids.com',  '555-2003', NOW())
ON CONFLICT (id) DO NOTHING;

-- 16) Plants (with QR codes)
INSERT INTO plants (id, exhibitor_id, judging_event_id, category_id, name, qr_code, notes, created_at) VALUES
  ('plant-001', 'exh-001', 'jevt-001', 'pcat-001', 'Cattleya labiata var. semi-alba',  'QR-A1B2C3D4E5F6', NULL, NOW()),
  ('plant-002', 'exh-002', 'jevt-001', 'pcat-002', 'Phalaenopsis equestris',            'QR-F6E5D4C3B2A1', 'Miniature species', NOW()),
  ('plant-003', 'exh-003', 'jevt-001', 'pcat-003', 'Dendrobium kingianum',               'QR-112233445566', 'Australian native', NOW()),
  ('plant-004', 'exh-001', 'jevt-001', 'pcat-001', 'Cattleya trianae',                   'QR-AABB11223344', 'Colombian species', NOW())
ON CONFLICT (id) DO NOTHING;

-- 17) Per-criterion Scores
INSERT INTO scores (id, plant_id, judge_id, criterion_id, value, choice, created_at) VALUES
  ('sc-001', 'plant-001', 'judge-001', 'crit-001', 30, NULL, NOW()),
  ('sc-002', 'plant-001', 'judge-001', 'crit-002', 32, NULL, NOW()),
  ('sc-003', 'plant-001', 'judge-001', 'crit-003', 28, NULL, NOW()),
  ('sc-004', 'plant-001', 'judge-002', 'crit-001', 28, NULL, NOW()),
  ('sc-005', 'plant-001', 'judge-002', 'crit-002', 30, NULL, NOW()),
  ('sc-006', 'plant-001', 'judge-002', 'crit-003', 27, NULL, NOW()),
  ('sc-007', 'plant-002', 'judge-001', 'crit-004', 26, NULL, NOW()),
  ('sc-008', 'plant-002', 'judge-001', 'crit-005', 28, NULL, NOW()),
  ('sc-009', 'plant-002', 'judge-001', 'crit-006', 25, NULL, NOW()),
  ('sc-010', 'plant-003', 'judge-003', 'crit-007', 24, NULL, NOW()),
  ('sc-011', 'plant-003', 'judge-003', 'crit-008', 27, NULL, NOW()),
  ('sc-012', 'plant-003', 'judge-003', 'crit-009', 26, NULL, NOW())
ON CONFLICT (id) DO NOTHING;
