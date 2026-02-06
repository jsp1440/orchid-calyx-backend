-- Calyx Seed Data (Postgres)
-- Seeds: 1 org, 1 show, roles+shifts, 6 volunteers+signups, attendance samples, 3 judges, 10 scores, 3 awards

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
INSERT INTO volunteer_roles (id, show_id, name, description, location, training_url, created_at) VALUES
  ('role-001', 'show-001', 'Admissions', 'Check tickets and guide visitors', 'Main Entrance', NULL, NOW()),
  ('role-002', 'show-001', 'Judging Assistant', 'Assist judges with scoring paperwork', 'Judging Hall B', 'https://example.com/judging-training', NOW()),
  ('role-003', 'show-001', 'Hospitality', 'Welcome guests, manage refreshments', 'Lobby & Lounge', NULL, NOW())
ON CONFLICT (id) DO NOTHING;

-- 5) Volunteer Shifts
INSERT INTO volunteer_shifts (id, show_id, role_id, shift_date, start_time, end_time, slots_needed, notes, created_at) VALUES
  ('shift-001', 'show-001', 'role-001', '2026-04-10', '08:00', '12:00', 3, 'Morning admissions', NOW()),
  ('shift-002', 'show-001', 'role-001', '2026-04-10', '12:00', '16:00', 3, 'Afternoon admissions', NOW()),
  ('shift-003', 'show-001', 'role-002', '2026-04-10', '09:00', '13:00', 2, 'Judging round 1', NOW()),
  ('shift-004', 'show-001', 'role-003', '2026-04-10', '08:00', '16:00', 4, 'All-day hospitality', NOW()),
  ('shift-005', 'show-001', 'role-002', '2026-04-11', '09:00', '13:00', 2, 'Judging round 2', NOW())
ON CONFLICT (id) DO NOTHING;

-- 6) Volunteers (6 total)
INSERT INTO volunteers (id, show_id, name, email, phone, status, created_at) VALUES
  ('vol-001', 'show-001', 'Alice Smith',    'alice@example.com',    '555-0101', 'approved', NOW()),
  ('vol-002', 'show-001', 'Bob Johnson',    'bob@example.com',      '555-0102', 'approved', NOW()),
  ('vol-003', 'show-001', 'Carol Williams', 'carol@example.com',    '555-0103', 'approved', NOW()),
  ('vol-004', 'show-001', 'Dave Brown',     'dave@example.com',     '555-0104', 'approved', NOW()),
  ('vol-005', 'show-001', 'Eve Davis',      'eve@example.com',      '555-0105', 'pending',  NOW()),
  ('vol-006', 'show-001', 'Frank Miller',   'frank@example.com',    '555-0106', 'approved', NOW())
ON CONFLICT (id) DO NOTHING;

-- 7) Volunteer Signups
INSERT INTO volunteer_signups (id, show_id, shift_id, volunteer_id, signup_source, approved, approved_by, approved_at, created_at) VALUES
  ('su-001', 'show-001', 'shift-001', 'vol-001', 'self',        true,  'coordinator', NOW(), NOW()),
  ('su-002', 'show-001', 'shift-001', 'vol-002', 'self',        true,  'coordinator', NOW(), NOW()),
  ('su-003', 'show-001', 'shift-002', 'vol-003', 'coordinator', true,  'coordinator', NOW(), NOW()),
  ('su-004', 'show-001', 'shift-003', 'vol-004', 'self',        true,  'coordinator', NOW(), NOW()),
  ('su-005', 'show-001', 'shift-003', 'vol-006', 'coordinator', true,  'coordinator', NOW(), NOW()),
  ('su-006', 'show-001', 'shift-004', 'vol-001', 'self',        true,  'coordinator', NOW(), NOW()),
  ('su-007', 'show-001', 'shift-004', 'vol-003', 'self',        false, NULL,          NULL,  NOW()),
  ('su-008', 'show-001', 'shift-002', 'vol-005', 'self',        false, NULL,          NULL,  NOW())
ON CONFLICT (id) DO NOTHING;

-- 8) Attendance samples
INSERT INTO volunteer_attendance (id, show_id, shift_id, volunteer_id, check_in_at, check_out_at, method, created_at) VALUES
  ('att-001', 'show-001', 'shift-001', 'vol-001', NOW() - INTERVAL '4 hours', NOW() - INTERVAL '30 minutes', 'qr',    NOW()),
  ('att-002', 'show-001', 'shift-001', 'vol-002', NOW() - INTERVAL '4 hours', NULL,                          'web',   NOW()),
  ('att-003', 'show-001', 'shift-003', 'vol-004', NOW() - INTERVAL '3 hours', NOW() - INTERVAL '1 hour',     'kiosk', NOW())
ON CONFLICT (id) DO NOTHING;

-- 9) Judges (3)
INSERT INTO judges (id, show_id, name, email, created_at) VALUES
  ('judge-001', 'show-001', 'Dr. Patricia Fielding', 'p.fielding@orchids.org', NOW()),
  ('judge-002', 'show-001', 'Robert Tanaka',         'r.tanaka@orchids.org',   NOW()),
  ('judge-003', 'show-001', 'Helen Marchetti',       'h.marchetti@orchids.org', NOW())
ON CONFLICT (id) DO NOTHING;

-- 10) Score Submissions (10 total across 5 entries x 2-3 judges)
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

-- 11) Awards (3, linked to entries)
INSERT INTO awards (id, entry_id, award_name, level, created_at) VALUES
  ('award-001', 'entry-004', 'Best Oncidium',    'Gold',   NOW()),
  ('award-002', 'entry-001', 'Best Cattleya',    'Silver', NOW()),
  ('award-003', 'entry-005', 'Judges Choice',    'Bronze', NOW())
ON CONFLICT (id) DO NOTHING;
