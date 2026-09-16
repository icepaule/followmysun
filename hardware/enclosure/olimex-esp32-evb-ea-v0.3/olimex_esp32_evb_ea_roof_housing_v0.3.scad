/*
  Olimex ESP32-EVB-EA Rev. L - roof/ceiling housing for shed interior
  Version: 0.3
  Designed from official OLIMEX Rev-L KiCad board coordinates.

  Installation concept:
    - Base plate is screwed to the underside of the shed roof.
    - PCB hangs below the base on 4 mm standoffs, component side downward.
    - Cover/lid comes from below and is retained by four M3 screws.
    - RST1 is operated by a separate printed side plunger.
    - UEXT1 is accessible through the downward-facing cover floor.
    - PWR1 is accessible through the right side wall.
    - WLAN antenna/pigtail exits through a nominal 10.0 mm front-wall hole.
    - CON1/CON2 actuator screw terminals get a right-side cable/service opening plus two bottom screwdriver windows.
    - USB-UART1 Micro-USB is accessible through the rear wall.
    - No CAN opening is provided.

  Default part for OpenSCAD preview: "preview"
  Export parts with -D 'part="base"', 'part="lid"', 'part="rst_button"', 'fit_test'.
*/

$fn = 64;
selected_part = is_undef(part) ? "preview" : part;

// Source board dimensions
pcb_w = 75.184;
pcb_h = 74.676;
pcb_t = 1.60;

// Rev-L board positions, converted to board-local coordinates from KiCad
// KiCad board minimum: X=69.596, Y=67.056
mh = [
    [71.374,  3.302],
    [71.374, 70.866],
    [ 3.810, 70.866]
];
pwr_pos  = [61.341, 50.513];
uext_pos = [31.750, 61.976];
rst_pos  = [ 5.588, 35.941];
usb_pos  = [63.404, 71.247];
con_pos = [
    [70.904, 29.718],
    [70.904, 14.718]
];

// Housing parameters
case_w = 94.0;
case_y = 92.0;
case_depth = 31.0;
wall = 2.6;
base_t = 3.0;
corner_r = 3.0;

pcb_standoff_h = 4.0;
pcb_z = base_t + pcb_standoff_h;
board_x = (case_w - pcb_w) / 2;
board_y = (case_y - pcb_h) / 2;

rim_clearance = 0.30;
rim_t = 1.40;
rim_h = 3.0;
lid_floor_t = 2.6;

lid_post_d = 6.2;
lid_post_pilot_d = 2.60;
lid_screw_clear_d = 3.40;
lid_post_xy = [
    [5.8, 5.8],
    [case_w-5.8, 5.8],
    [5.8, case_y-5.8],
    [case_w-5.8, case_y-5.8]
];

pcb_post_d = 6.0;
pcb_post_pilot_d = 2.70;
mount_tab_len = 13.0;
mount_tab_w = 18.0;
mount_hole_d = 4.5;
mount_hole_edge = 7.0;
mount_tab_y = [17.0, case_y-17.0];

// Openings / user-adjustable fit values
antenna_hole_d = 10.0;
antenna_x = case_w * 0.48;
antenna_z = 16.0;

pwr_open_y = 11.0;
pwr_open_z = 11.0;
pwr_z0 = pcb_z - 0.5;

uext_open_x = 16.0;
uext_open_y = 7.0;

usb_open_x = 13.0;
usb_open_z = 8.5;
usb_z0 = pcb_z + pcb_t - 1.0;

terminal_side_clear = 0.8;
terminal_block_half_len = 8.25;
terminal_side_z0 = pcb_z + pcb_t - 1.0;
terminal_side_z = 13.5;
terminal_floor_x = 13.0;
terminal_floor_y = 14.0;
terminal_side_y = abs(con_pos[0][1]-con_pos[1][1]) + 2*(terminal_block_half_len + terminal_side_clear);

rst_hole_d = 4.2;
rst_axis_z = pcb_z + 1.7;
rst_cap_d = 8.0;
rst_cap_t = 2.4;
rst_shaft_d = 3.55;
rst_shaft_len = 11.0;
rst_barb_d = 4.55;
rst_barb_h = 1.0;

ventilation = true;
vent_slot_len = 18.0;
vent_slot_w = 2.2;

module rounded_tab(size=[13,18,3], r=3) {
    hull() {
        for (x=[r, size[0]-r], y=[r, size[1]-r])
            translate([x,y,0]) cylinder(h=size[2], r=r);
    }
}

module ring_rect(outer=[88,86], t=1.4, h=3) {
    difference() {
        cube([outer[0], outer[1], h]);
        translate([t,t,-0.1]) cube([outer[0]-2*t, outer[1]-2*t, h+0.2]);
    }
}

module base() {
    difference() {
        union() {
            cube([case_w, case_y, base_t]);
            for (yy = mount_tab_y) {
                translate([-mount_tab_len, yy-mount_tab_w/2, 0])
                    rounded_tab([mount_tab_len+1.0, mount_tab_w, base_t], corner_r);
                translate([case_w-1.0, yy-mount_tab_w/2, 0])
                    rounded_tab([mount_tab_len+1.0, mount_tab_w, base_t], corner_r);
            }
            translate([wall+rim_clearance, wall+rim_clearance, base_t])
                ring_rect(
                    [case_w-2*(wall+rim_clearance), case_y-2*(wall+rim_clearance)],
                    rim_t, rim_h
                );
            for (p = mh)
                translate([board_x+p[0], board_y+p[1], base_t])
                    cylinder(h=pcb_standoff_h, d=pcb_post_d);
            for (p = lid_post_xy)
                translate([p[0], p[1], base_t])
                    cylinder(h=case_depth-lid_floor_t-base_t-1.0, d=lid_post_d);
        }

        for (yy = mount_tab_y) {
            translate([-mount_hole_edge, yy, -0.5])
                cylinder(h=base_t+1.0, d=mount_hole_d);
            translate([case_w+mount_hole_edge, yy, -0.5])
                cylinder(h=base_t+1.0, d=mount_hole_d);
        }
        for (p = mh)
            translate([board_x+p[0], board_y+p[1], base_t-0.2])
                cylinder(h=pcb_standoff_h+0.5, d=pcb_post_pilot_d);
        for (p = lid_post_xy)
            translate([p[0], p[1], case_depth-lid_floor_t-9.0])
                cylinder(h=10.0, d=lid_post_pilot_d);
    }
}

module lid_assembly() {
    pwr_y_world = board_y + pwr_pos[1];
    uext_x_world = board_x + uext_pos[0];
    uext_y_world = board_y + uext_pos[1];
    rst_y_world = board_y + rst_pos[1];
    usb_x_world = board_x + usb_pos[0];
    con_x_world = board_x + con_pos[0][0];
    con_y_lo = board_y + min(con_pos[0][1], con_pos[1][1]) - terminal_block_half_len - terminal_side_clear;
    con_y_hi = board_y + max(con_pos[0][1], con_pos[1][1]) + terminal_block_half_len + terminal_side_clear;

    difference() {
        translate([0,0,base_t])
            cube([case_w, case_y, case_depth-base_t]);
        translate([wall, wall, base_t-0.2])
            cube([case_w-2*wall, case_y-2*wall,
                  case_depth-base_t-lid_floor_t+0.2]);
        translate([case_w-wall-0.2,
                   pwr_y_world-pwr_open_y/2,
                   pwr_z0])
            cube([wall+0.6, pwr_open_y, pwr_open_z]);
        translate([case_w-wall-0.2, con_y_lo, terminal_side_z0])
            cube([wall+0.6, con_y_hi-con_y_lo, terminal_side_z]);
        translate([usb_x_world-usb_open_x/2, case_y-wall-0.2, usb_z0])
            cube([usb_open_x, wall+0.6, usb_open_z]);
        translate([-0.5, rst_y_world, rst_axis_z])
            rotate([0,90,0])
                cylinder(h=wall+1.0, d=rst_hole_d);
        translate([antenna_x, wall+0.5, antenna_z])
            rotate([90,0,0])
                cylinder(h=wall+1.0, d=antenna_hole_d);
        translate([uext_x_world-uext_open_x/2,
                   uext_y_world-uext_open_y/2,
                   case_depth-lid_floor_t-0.3])
            cube([uext_open_x, uext_open_y, lid_floor_t+0.6]);
        for (cp = con_pos)
            translate([con_x_world-terminal_floor_x/2,
                       board_y+cp[1]-terminal_floor_y/2,
                       case_depth-lid_floor_t-0.3])
                cube([terminal_floor_x, terminal_floor_y, lid_floor_t+0.6]);
        for (p = lid_post_xy)
            translate([p[0], p[1], case_depth-lid_floor_t-0.3])
                cylinder(h=lid_floor_t+0.6, d=lid_screw_clear_d);
        if (ventilation) {
            for (yy=[24, 31, 38])
                translate([case_w/2-vent_slot_len/2, yy-vent_slot_w/2,
                           case_depth-lid_floor_t-0.3])
                    cube([vent_slot_len, vent_slot_w, lid_floor_t+0.6]);
        }
    }
}

module lid() {
    translate([0,case_y,case_depth])
        rotate([180,0,0])
            lid_assembly();
}

module rst_button() {
    union() {
        cylinder(h=rst_cap_t, d=rst_cap_d);
        translate([0,0,rst_cap_t])
            cylinder(h=rst_shaft_len-rst_barb_h, d=rst_shaft_d);
        translate([0,0,rst_cap_t+rst_shaft_len-rst_barb_h])
            cylinder(h=rst_barb_h, d1=rst_shaft_d, d2=rst_barb_d);
    }
}

module pcb_mock() {
    difference() {
        linear_extrude(pcb_t)
            difference() {
                square([pcb_w,pcb_h]);
                translate([-0.1,-0.1]) square([19.658,6.196]);
                translate([58.674,pcb_h-1.116]) square([9.525,1.216]);
            }
        for (p=mh)
            translate([p[0],p[1],-0.1]) cylinder(h=pcb_t+0.2,d=3.3);
    }
}

module component_markers() {
    translate([board_x+uext_pos[0]-8, board_y+uext_pos[1]-5, pcb_z+pcb_t])
        cube([16,10,8]);
    translate([board_x+pwr_pos[0]-5, board_y+pwr_pos[1]-6, pcb_z+pcb_t])
        cube([18,12,10]);
    for (cp = con_pos)
        translate([board_x+cp[0]-4.2, board_y+cp[1]-8.25, pcb_z+pcb_t])
            cube([8.4,16.5,10.0]);
    translate([board_x+usb_pos[0]-4.0, board_y+usb_pos[1]-3.4, pcb_z+pcb_t])
        cube([8.0,6.8,3.2]);
    translate([board_x+rst_pos[0]-3, board_y+rst_pos[1]-2, pcb_z+pcb_t])
        cube([6,4,2.5]);
}

module rst_button_assembly() {
    rst_y_world = board_y + rst_pos[1];
    translate([-rst_cap_t, rst_y_world, rst_axis_z])
        rotate([0,90,0])
            rst_button();
}

module fit_test() {
    coupon_w = 154;
    coupon_h = 38;
    difference() {
        cube([coupon_w,coupon_h,3]);
        translate([10,19,-0.2]) cylinder(h=3.4,d=antenna_hole_d);
        translate([25,19,-0.2]) cylinder(h=3.4,d=rst_hole_d);
        translate([36,19-pwr_open_z/2,-0.2]) cube([pwr_open_y,pwr_open_z,3.4]);
        translate([59-uext_open_x/2,19-uext_open_y/2,-0.2]) cube([uext_open_x,uext_open_y,3.4]);
        translate([82-usb_open_x/2,19-usb_open_z/2,-0.2]) cube([usb_open_x,usb_open_z,3.4]);
        translate([105-terminal_floor_x/2,19-terminal_floor_y/2,-0.2]) cube([terminal_floor_x,terminal_floor_y,3.4]);
        translate([119,19-terminal_side_z/2,-0.2]) cube([terminal_side_y,terminal_side_z,3.4]);
    }
}

module preview() {
    color("LightGray") base();
    color([0.0,0.45,0.10])
        translate([board_x,board_y,pcb_z]) pcb_mock();
    color("DimGray") component_markers();
    color([0.82,0.85,0.90,0.35]) lid_assembly();
    color("Orange") rst_button_assembly();
}

module exploded() {
    color("LightGray") base();
    color([0.0,0.45,0.10])
        translate([board_x,board_y,pcb_z]) pcb_mock();
    color("DimGray") component_markers();
    color([0.82,0.85,0.90,0.60]) translate([0,0,15]) lid_assembly();
    color("Orange") translate([-12,0,0]) rst_button_assembly();
}

if (selected_part == "base") base();
else if (selected_part == "lid") lid();
else if (selected_part == "rst_button") rst_button();
else if (selected_part == "fit_test") fit_test();
else if (selected_part == "exploded") exploded();
else preview();
