#!/usr/bin/env python3
"""
Generates a broader, diverse synthetic incident dataset for classification
training/reference -- covering categories the real ServiceNow demo data
and our original 8-ticket sample don't have enough volume in. This is
labeled and documented as SYNTHETIC throughout, never presented as real.

Usage: python generate_synthetic_dataset.py > synthetic_incidents.json
"""
import json
import random

random.seed(42)  # reproducible output

# Each category: (category, subcategory, priority, assignment_group, templates)
# templates: list of (short_description, description, resolution) tuples.
# Some resolutions are "" (still open) to mirror a realistic open/closed mix.
CATEGORIES = [
    ("Network", "VPN", "Medium", "Network Support", [
        ("VPN drops every few minutes on Cisco AnyConnect", "User reports the VPN tunnel disconnects repeatedly during work hours, requiring manual reconnection each time.", "MTU mismatch causing packet fragmentation; lowered client MTU to 1400 and enabled TCP MSS clamping."),
        ("Cannot establish VPN connection from home network", "User's home ISP appears to block the VPN port; connection attempt times out immediately.", "Switched VPN client to TLS-based port 443 fallback; connectivity restored."),
        ("Slow file transfer speeds over VPN for remote team", "Multiple remote sales team members report large file uploads take 10x longer than expected.", ""),
    ]),
    ("Network", "WiFi", "Low", "Network Support", [
        ("Conference room WiFi keeps disconnecting", "Guests in the 3rd floor conference room report repeated WiFi drops during video calls.", "Replaced a failing access point; signal now stable."),
        ("Cannot see corporate WiFi SSID on new laptop", "New laptop doesn't list the corporate SSID in available networks.", "WiFi adapter driver was outdated; updated driver and SSID appeared."),
    ]),
    ("Account Access", "Password Reset", "Medium", "Service Desk", [
        ("Locked out after 5 failed login attempts", "User's account locked after mistyping password multiple times this morning.", "Verified identity via security questions, unlocked account, issued temporary password."),
        ("Password expired, cannot log into laptop remotely", "User's Windows password expired over the weekend; cannot reset remotely without VPN access first.", ""),
        ("MFA app not generating codes after phone replacement", "User got a new phone and the authenticator app no longer has their MFA seed.", "Re-enrolled user's MFA on the new device after identity verification."),
    ]),
    ("Account Access", "Onboarding", "Medium", "Service Desk", [
        ("New hire starting Monday needs full account provisioning", "New employee needs AD account, mailbox, VPN access, and standard software before their start date.", "Provisioned from onboarding template; confirmed access with hiring manager."),
        ("Contractor needs temporary limited-scope access", "External contractor needs read-only access to one SharePoint site for a 90-day engagement.", "Created a scoped guest account with a 90-day expiry."),
    ]),
    ("Email", "Access", "Low", "Email Support", [
        ("Cannot open shared support mailbox in Outlook", "User gets 'Cannot expand the folder' error opening the shared support@company.com mailbox.", "Shared mailbox permissions hadn't propagated; re-applied Full Access permissions."),
        ("Emails to external domain bouncing as spam", "User's emails to a specific partner company are being rejected as spam by the recipient's server.", ""),
        ("Mailbox over quota, cannot send or receive", "User's mailbox hit its storage quota and is rejecting new mail.", "Archived mail older than 1 year to a PST; quota freed up."),
    ]),
    ("Hardware", "Printer", "Low", "Desktop Support", [
        ("Finance floor shared printer offline for everyone", "Printer HP-FIN-03 shows offline status; whole floor cannot print.", "Printer lost its DHCP-reserved IP after a switch reboot; reassigned and restarted spooler."),
        ("New laptop won't detect any USB peripherals", "User's new laptop doesn't recognize mouse, keyboard dock, or external drive via USB-C hub.", "USB-C hub firmware was outdated; updated firmware resolved detection."),
    ]),
    ("Hardware", "Laptop", "Medium", "Desktop Support", [
        ("Laptop battery draining fully within an hour", "User's 1-year-old laptop battery no longer holds a charge beyond ~50 minutes.", "Battery health test confirmed degradation below 60% capacity; replacement ordered."),
        ("Laptop screen flickering intermittently", "Screen flickers randomly, worse when the laptop is plugged into external power.", ""),
    ]),
    ("Software", "Application Crash", "High", "Application Support", [
        ("Finance reporting tool crashes on month-end close", "The monthly close report generator crashes with an out-of-memory error every month-end, blocking close.", "Increased the app server's memory allocation and optimized the report query; verified on next close cycle."),
        ("CRM freezes when opening large customer records", "Sales reps report the CRM UI freezes for 30+ seconds opening any account with 500+ activity records.", ""),
    ]),
    ("Software", "Licensing", "Medium", "Application Support", [
        ("Design team hitting seat limit on Adobe Creative Cloud", "New designer cannot activate Adobe apps -- team has hit its license seat limit.", "Reclaimed an unused seat from a departed employee's account and reassigned it."),
    ]),
    ("Security", "Phishing", "High", "Security Operations", [
        ("Employee reported a suspicious invoice email", "User forwarded a suspicious email claiming to be an overdue invoice with a link to 'verify payment'.", "Confirmed phishing, blocked sender domain, and sent a company-wide advisory."),
        ("Possible credential compromise after phishing click", "User clicked a link in a phishing email and entered their password on the fake login page before realizing.", "Force-reset the user's password, revoked all active sessions, and reviewed account activity for anomalies -- no unauthorized access found."),
    ]),
    ("Security", "Access Review", "Medium", "Security Operations", [
        ("Departed employee's account still shows as active", "Quarterly access review found a former employee's account was not disabled on their last day.", "Disabled the account immediately and opened a process review for the offboarding checklist."),
    ]),
    ("Database", "Performance", "High", "Database Administration", [
        ("Order processing database queries running 10x slower", "Since this morning, order lookups that normally take 200ms are taking 2+ seconds, causing checkout delays.", "Identified a missing index on the orders table after a schema migration; added the index, latency returned to normal."),
        ("Nightly backup job failing for the last 3 days", "The automated nightly database backup has failed silently for three consecutive nights.", ""),
    ]),
    ("Infrastructure", "Kubernetes", "High", "Platform Engineering", [
        ("Pod stuck in CrashLoopBackOff after deployment", "The checkout-service pod enters CrashLoopBackOff immediately after the latest deployment.", "Rolled back to the previous image version; root cause was a missing environment variable in the new config."),
        ("Node running out of disk space, pods evicted", "A worker node hit disk pressure and Kubernetes began evicting pods to reclaim space.", "Cleared unused container images and increased the node's disk allocation."),
        ("Namespace resource quota exceeded, new pods pending", "New deployments to the analytics namespace are stuck Pending because the CPU quota is exhausted.", ""),
    ]),
    ("Infrastructure", "Cloud Storage", "Medium", "Platform Engineering", [
        ("S3 bucket access denied for reporting service", "The reporting service started getting AccessDenied errors reading from its S3 bucket after an IAM policy update.", "Corrected an overly restrictive IAM policy condition that was added during a security hardening pass."),
    ]),
    ("Collaboration", "Video Conferencing", "Low", "Desktop Support", [
        ("Camera not detected in Teams meetings", "User's laptop camera works in other apps but Teams shows 'no camera found'.", "Teams had cached an old camera driver reference; cleared cache and camera was detected."),
    ]),
    ("Facilities", "Badge Access", "Medium", "Facilities", [
        ("Badge no longer opens 4th floor secure lab", "Employee's access badge stopped working on the 4th floor secure lab door after a recent role change.", "Access group had been removed during the role change; re-added the correct access group."),
    ]),
]


def build_dataset():
    records = []
    counter = 20000
    for category, subcategory, priority, group, templates in CATEGORIES:
        for short_desc, desc, resolution in templates:
            counter += 1
            records.append({
                "id": f"SYN{counter:07d}",
                "source": "synthetic",
                "short_description": short_desc,
                "description": desc,
                "category": category,
                "subcategory": subcategory,
                "priority": priority,
                "assignment_group": group,
                "status": "Closed" if resolution else "Open",
                "resolution": resolution,
            })
    random.shuffle(records)
    return records


if __name__ == "__main__":
    print(json.dumps(build_dataset(), indent=2))
