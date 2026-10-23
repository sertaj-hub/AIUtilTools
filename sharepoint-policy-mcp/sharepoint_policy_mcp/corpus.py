"""An in-memory stand-in for the policy libraries on a SharePoint site.

Exists so you can run the server, wire it into Claude Code and exercise every
tool before anyone issues you an Entra ID app registration. The sections are
long enough and formulaic enough that ranking tests against them are
meaningful rather than decorative.

THE CONTENT IS SYNTHETIC. It is written to read like a BSA/AML program policy
and like QA and QC procedures, and the statutory deadlines in it are the real
ones, but it is illustrative scaffolding for testing retrieval -- not your
institution's policy, and not legal advice. Replace it with the real corpus
through the Graph ingestion pipeline; do not let it answer a real question.
"""

from __future__ import annotations

from .models import Document, Section

MOCK_SITE = "https://mock.sharepoint.com/sites/aml-policy"

# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------

DOCUMENTS: tuple[Document, ...] = (
    Document(
        policy_id="BSA-001",
        title="BSA/AML Compliance Program Policy",
        version="4.2",
        library="BSA Policies",
        doc_type="BSA",
        effective_date="2026-07-01",
        last_modified="2026-06-18",
        owner="BSA Officer",
        url=f"{MOCK_SITE}/BSA%20Policies/BSA-001%20Program%20Policy%20v4.2.docx",
    ),
    Document(
        policy_id="BSA-001",
        title="BSA/AML Compliance Program Policy",
        version="4.1",
        library="BSA Policies",
        doc_type="BSA",
        effective_date="2025-07-01",
        last_modified="2025-06-20",
        owner="BSA Officer",
        url=f"{MOCK_SITE}/BSA%20Policies/Archive/BSA-001%20Program%20Policy%20v4.1.docx",
        superseded=True,
    ),
    Document(
        policy_id="QA-014",
        title="Alert and Case Quality Assurance Policy",
        version="2.1",
        library="QA Policies",
        doc_type="QA",
        effective_date="2026-04-01",
        last_modified="2026-03-24",
        owner="Head of AML Quality Assurance",
        url=f"{MOCK_SITE}/QA%20Policies/QA-014%20Alert%20and%20Case%20QA%20v2.1.docx",
    ),
    Document(
        policy_id="QC-009",
        title="Case Quality Control and Pre-Filing Review Policy",
        version="1.7",
        library="QC Policies",
        doc_type="QC",
        effective_date="2026-02-15",
        last_modified="2026-02-03",
        owner="AML Quality Control Manager",
        url=f"{MOCK_SITE}/QC%20Policies/QC-009%20Pre-Filing%20Review%20v1.7.docx",
    ),
    # Present so that entitlement trimming has something to trim. An analyst
    # asking a liaison question should be told the answer exists and is not
    # theirs to read -- not handed the passage, and not told nothing exists.
    Document(
        policy_id="QC-022",
        title="Law Enforcement Liaison and Subpoena Handling Procedures",
        version="1.2",
        library="QC Policies",
        doc_type="QC",
        effective_date="2026-01-05",
        last_modified="2025-12-19",
        owner="BSA Officer",
        url=f"{MOCK_SITE}/QC%20Policies/Restricted/QC-022%20LE%20Liaison%20v1.2.docx",
        audience=("aml-manager", "bsa-officer"),
    ),
)


def _s(policy_id: str, version: str, number: str, heading: str, text: str,
       audience: tuple[str, ...] = ()) -> Section:
    return Section(
        section_id=f"{policy_id}@{version}#{number}",
        policy_id=policy_id,
        number=number,
        heading=heading,
        text=" ".join(text.split()),
        audience=audience,
    )


# --------------------------------------------------------------------------
# BSA-001 v4.2 -- the current program policy
# --------------------------------------------------------------------------

_BSA_42 = (
    _s("BSA-001", "4.2", "1.0", "Purpose and Scope", """
        This policy establishes the Bank Secrecy Act and anti-money laundering
        compliance program applicable to all business lines, subsidiaries and
        employees. It sets the minimum standards for customer due diligence,
        transaction monitoring, investigation, suspicious activity reporting
        and recordkeeping. Business units may adopt stricter standards but may
        not adopt weaker ones. Deviation from this policy requires written
        approval from the BSA Officer and is reported to the Board AML
        Committee at its next scheduled meeting.
    """),
    _s("BSA-001", "4.2", "2.0", "Program Pillars and Governance", """
        The program rests on five pillars: a system of internal controls; an
        independent testing function; a designated BSA Officer with sufficient
        authority and resources; ongoing training for relevant personnel; and
        risk-based customer due diligence. The BSA Officer reports functionally
        to the Chief Compliance Officer and has a direct reporting line to the
        Board AML Committee. The Board approves this policy at least annually
        and approves any material change on an exception basis.
    """),
    _s("BSA-001", "4.2", "3.0", "Customer Due Diligence and Beneficial Ownership", """
        At account opening the institution identifies and verifies each legal
        entity customer and collects beneficial ownership information for each
        individual owning 25 percent or more of the equity interests, together
        with one individual with significant responsibility for controlling or
        managing the entity. Customer risk ratings are assigned at onboarding
        and refreshed on a risk-based cycle: high risk annually, medium risk
        every two years, low risk every three years, and on any trigger event
        such as a material change in expected activity.
    """),
    _s("BSA-001", "4.2", "4.0", "Enhanced Due Diligence for Higher-Risk Customers", """
        Enhanced due diligence applies to customers presenting elevated risk,
        including politically exposed persons and their close associates,
        correspondent banking relationships, money services businesses, cash
        intensive businesses and customers in higher-risk jurisdictions.
        Enhanced due diligence requires documented source of wealth and source
        of funds, senior management approval to open or retain the
        relationship, and enhanced ongoing monitoring with a documented review
        at least annually.
    """),
    _s("BSA-001", "4.2", "5.0", "Suspicious Activity Detection and Escalation", """
        Transaction monitoring generates alerts which are triaged by the first
        line within five business days of generation. An alert that cannot be
        cleared on documented grounds is escalated to a case for
        investigation. The investigator assembles transactional evidence,
        customer profile information and any prior filings, and makes a
        documented recommendation to file or not to file. A decision not to
        file must record the facts considered and the reasoning, to the same
        standard as a decision to file.
    """),
    _s("BSA-001", "4.2", "5.1", "SAR Filing Deadlines", """
        A suspicious activity report is filed with FinCEN within 30 calendar
        days of initial detection of facts that may constitute a basis for
        filing. Where no suspect has been identified on the date of initial
        detection, the institution may take an additional 30 calendar days to
        identify a suspect, but filing must occur no later than 60 calendar
        days after initial detection. Initial detection is the date the
        institution first has information sufficient to establish a basis for
        filing, not the date an alert was generated. Where suspicious activity
        continues, a continuing activity report is filed within 120 calendar
        days of the date of the previous filing.
    """),
    _s("BSA-001", "4.2", "5.2", "Prohibition on Disclosure", """
        No employee may disclose to the subject of a suspicious activity
        report, or to any person not entitled to the information, that a report
        has been prepared, filed or contemplated. Requests for information
        about a filing from outside the institution are referred to the BSA
        Officer without substantive response. This prohibition is permanent and
        survives the employee's departure.
    """),
    _s("BSA-001", "4.2", "6.0", "Currency Transaction Reporting", """
        A currency transaction report is filed for each transaction in currency
        of more than 10,000 dollars conducted by or on behalf of the same person
        on the same business day, aggregating multiple transactions where
        required. Filing occurs within 15 calendar days of the transaction
        date. Exemptions for eligible non-listed businesses and payroll
        customers are reviewed and re-certified annually. Structuring to evade
        a reporting requirement is itself reportable as suspicious activity.
    """),
    _s("BSA-001", "4.2", "7.0", "Information Sharing under Sections 314(a) and 314(b)", """
        Upon receipt of a FinCEN 314(a) request the institution searches its
        records for accounts and transactions involving each named subject and
        responds within 14 calendar days of the posting date. A 314(a) search
        is not by itself a basis for filing and does not require closure of the
        account. Participation in voluntary information sharing under 314(b)
        requires annual notice to FinCEN, verification that the counterparty
        institution's notice is current, and documentation of each exchange in
        the case record.
    """),
    _s("BSA-001", "4.2", "8.0", "Recordkeeping and Retention", """
        A copy of each filed suspicious activity report and all supporting
        documentation is retained for five years from the date of filing.
        Supporting documentation includes the alert, the investigative record,
        transaction data relied upon and the filing decision rationale.
        Currency transaction reports and customer identification records are
        retained for five years. Records are produced to FinCEN or an
        examining agency upon request without a subpoena.
    """),
    _s("BSA-001", "4.2", "9.0", "Training", """
        All employees receive general anti-money laundering awareness training
        within 30 days of hire and annually thereafter. Staff in first-line
        investigation, quality assurance, quality control and transaction
        monitoring receive role-specific training annually covering typologies,
        system changes and regulatory developments. Completion is tracked and
        unremediated non-completion is escalated to the employee's manager and
        reported to the Board AML Committee.
    """),
    _s("BSA-001", "4.2", "10.0", "Independent Testing", """
        The program is independently tested at least annually by internal audit
        or a qualified external party, on a scope proportionate to the
        institution's risk profile. Testing covers the adequacy of the risk
        assessment, the effectiveness of transaction monitoring coverage and
        tuning, the timeliness and quality of filings, and the remediation of
        prior findings. Results are reported to the Board AML Committee, and
        findings are tracked to closure with documented management responses.
    """),
)

# --------------------------------------------------------------------------
# BSA-001 v4.1 -- superseded, retained so version comparison has two sides
# --------------------------------------------------------------------------

_BSA_41 = (
    _s("BSA-001", "4.1", "1.0", "Purpose and Scope", """
        This policy establishes the Bank Secrecy Act and anti-money laundering
        compliance program applicable to all business lines, subsidiaries and
        employees. It sets the minimum standards for customer due diligence,
        transaction monitoring, investigation, suspicious activity reporting
        and recordkeeping. Business units may adopt stricter standards but may
        not adopt weaker ones. Deviation from this policy requires written
        approval from the BSA Officer.
    """),
    _s("BSA-001", "4.1", "2.0", "Program Pillars and Governance", """
        The program rests on five pillars: a system of internal controls; an
        independent testing function; a designated BSA Officer with sufficient
        authority and resources; ongoing training for relevant personnel; and
        risk-based customer due diligence. The BSA Officer reports functionally
        to the Chief Compliance Officer and has a direct reporting line to the
        Board AML Committee. The Board approves this policy at least annually
        and approves any material change on an exception basis.
    """),
    _s("BSA-001", "4.1", "3.0", "Customer Due Diligence and Beneficial Ownership", """
        At account opening the institution identifies and verifies each legal
        entity customer and collects beneficial ownership information for each
        individual owning 25 percent or more of the equity interests, together
        with one individual with significant responsibility for controlling or
        managing the entity. Customer risk ratings are assigned at onboarding
        and refreshed every two years regardless of risk rating, and on any
        trigger event such as a material change in expected activity.
    """),
    _s("BSA-001", "4.1", "4.0", "Enhanced Due Diligence for Higher-Risk Customers", """
        Enhanced due diligence applies to customers presenting elevated risk,
        including politically exposed persons and their close associates,
        correspondent banking relationships, money services businesses and
        customers in higher-risk jurisdictions. Enhanced due diligence requires
        documented source of wealth, senior management approval to open the
        relationship, and enhanced ongoing monitoring.
    """),
    _s("BSA-001", "4.1", "5.0", "Suspicious Activity Detection and Escalation", """
        Transaction monitoring generates alerts which are triaged by the first
        line within ten business days of generation. An alert that cannot be
        cleared on documented grounds is escalated to a case for
        investigation. The investigator assembles transactional evidence,
        customer profile information and any prior filings, and makes a
        documented recommendation to file or not to file.
    """),
    _s("BSA-001", "4.1", "5.1", "SAR Filing Deadlines", """
        A suspicious activity report is filed with FinCEN within 30 calendar
        days of initial detection of facts that may constitute a basis for
        filing. Where no suspect has been identified on the date of initial
        detection, the institution may take an additional 30 calendar days to
        identify a suspect, but filing must occur no later than 60 calendar
        days after initial detection. Where suspicious activity continues, a
        continuing activity report is filed within 120 calendar days of the
        date of the previous filing.
    """),
    _s("BSA-001", "4.1", "6.0", "Currency Transaction Reporting", """
        A currency transaction report is filed for each transaction in currency
        of more than 10,000 dollars conducted by or on behalf of the same person
        on the same business day, aggregating multiple transactions where
        required. Filing occurs within 15 calendar days of the transaction
        date. Structuring to evade a reporting requirement is itself reportable
        as suspicious activity.
    """),
    _s("BSA-001", "4.1", "8.0", "Recordkeeping and Retention", """
        A copy of each filed suspicious activity report and all supporting
        documentation is retained for five years from the date of filing.
        Currency transaction reports and customer identification records are
        retained for five years.
    """),
    _s("BSA-001", "4.1", "9.0", "Training", """
        All employees receive general anti-money laundering awareness training
        within 30 days of hire and annually thereafter. Completion is tracked
        and unremediated non-completion is escalated to the employee's manager.
    """),
    _s("BSA-001", "4.1", "10.0", "Independent Testing", """
        The program is independently tested at least annually by internal audit
        or a qualified external party. Results are reported to the Board AML
        Committee, and findings are tracked to closure.
    """),
)

# --------------------------------------------------------------------------
# QA-014 v2.1 -- post-decision quality assurance
# --------------------------------------------------------------------------

_QA_21 = (
    _s("QA-014", "2.1", "1.0", "Purpose and Relationship to Quality Control", """
        Quality assurance is a post-decision, sample-based assessment of
        completed alert and case work. It is distinct from quality control,
        which is a pre-filing review of individual cases described in QC-009.
        Quality assurance exists to measure and improve the reliability of
        investigative decisions across the population; it does not re-decide
        individual cases and does not reverse a filing decision.
    """),
    _s("QA-014", "2.1", "2.0", "Sample Selection and Coverage", """
        A minimum of 10 percent of closed alerts and 15 percent of closed cases
        are sampled each month, with a floor of five items per analyst per
        month so that every analyst receives feedback regardless of volume.
        Sampling is stratified across analyst, alert typology, risk rating and
        disposition, and is weighted toward no-file decisions, which carry the
        greater regulatory consequence if wrong. Selection is performed by the
        quality assurance function and is not visible to analysts in advance.
    """),
    _s("QA-014", "2.1", "3.0", "Scoring Rubric and Error Categories", """
        Each sampled item is scored against four dimensions: completeness of
        research, soundness of the disposition, quality of the written
        rationale, and adherence to procedure and timeliness. Findings are
        classified as critical, major or minor. An item with any critical
        finding scores zero overall regardless of its other dimensions,
        because a correct narrative attached to a wrong disposition is not a
        partial success.
    """),
    _s("QA-014", "2.1", "4.0", "Critical Error Definitions", """
        A critical error is any of the following: a decision not to file where
        the evidence in the case record supported filing; a missed filing
        deadline; failure to review an identified related party or related
        account; failure to escalate activity meeting a mandatory escalation
        trigger; or disclosure of the existence of a filing to an unauthorised
        person. Critical errors are reported to the BSA Officer within two
        business days of identification and trigger a lookback over the
        analyst's prior 90 days of no-file decisions.
    """),
    _s("QA-014", "2.1", "5.0", "Rebuttal and Dispute Process", """
        An analyst may rebut a finding within five business days of receiving
        the scorecard, in writing, citing the evidence in the case record. The
        quality assurance reviewer responds within five business days.
        Unresolved disputes are escalated to the Head of Quality Assurance and
        the analyst's manager jointly, whose decision is final and recorded.
        Rebuttal rates and overturn rates are themselves reported, since a high
        overturn rate indicates a rubric problem rather than an analyst
        problem.
    """),
    _s("QA-014", "2.1", "6.0", "Reporting and Trend Analysis", """
        Quality assurance results are reported monthly to AML Operations
        management and quarterly to the Board AML Committee. Reporting covers
        error rates by category, by analyst team and by alert typology, and
        trends against the prior four quarters. A sustained rise in a single
        error category is treated as a systemic signal and is referred for root
        cause analysis rather than addressed analyst by analyst.
    """),
    _s("QA-014", "2.1", "7.0", "Remediation and Retraining Thresholds", """
        An analyst scoring below 90 percent in a month receives targeted
        coaching from their manager. Below 80 percent, or any critical error,
        triggers a formal remediation plan with increased sampling at 25
        percent of that analyst's output for the following three months. Two
        consecutive months below 80 percent are escalated to Human Resources
        and the analyst's authority to close alerts without review is
        suspended pending remediation.
    """),
)

# --------------------------------------------------------------------------
# QC-009 v1.7 -- pre-filing quality control
# --------------------------------------------------------------------------

_QC_17 = (
    _s("QC-009", "1.7", "1.0", "Purpose and Scope", """
        Quality control is a pre-filing review performed on every case with a
        recommendation to file a suspicious activity report, and on a
        risk-based sample of cases recommended for closure without filing. The
        purpose is to catch defects before a report reaches FinCEN, when they
        can still be corrected without a continuing activity filing or an
        amendment.
    """),
    _s("QC-009", "1.7", "2.0", "Pre-Filing Checklist", """
        Before a filing is released the reviewer confirms: the subject and all
        related parties are correctly identified and spelled as they appear in
        the system of record; every transaction cited in the narrative is
        evidenced in the case file; the aggregate amount in the narrative
        reconciles to the transaction schedule; prior filings on the same
        subject are referenced and the continuing activity box is set
        correctly; all mandatory FinCEN fields are populated; and the filing
        deadline calculated from initial detection has not passed and will not
        pass before release.
    """),
    _s("QC-009", "1.7", "3.0", "Narrative Standards", """
        The narrative states who, what, when, where, why and how, in plain
        chronological English, and is intelligible to a reader with no access
        to the case file. It describes the activity and the reason it is
        suspicious without asserting that a crime occurred, avoids internal
        system names, codes and abbreviations, and does not reproduce the
        institution's internal risk scores. Conclusory statements unsupported
        by described facts are a quality control failure and are returned to
        the investigator.
    """),
    _s("QC-009", "1.7", "4.0", "Four-Eyes Review and Segregation of Duties", """
        No person may review their own work. The quality control reviewer is
        independent of the investigation and does not report to the
        investigator's line manager. Where resource constraints make this
        impossible, the review is performed by the BSA Officer or a delegate
        and the constraint is documented. Approval of release is recorded with
        the reviewer's identity and timestamp in the case management system.
    """),
    _s("QC-009", "1.7", "5.0", "Escalation of Quality Control Failures", """
        A case returned twice for the same defect is escalated to the
        investigator's manager. A defect that would have caused a late filing,
        an incorrect subject, or an unsupported conclusion in a filed narrative
        is reported to the quality assurance function for inclusion in trend
        analysis under QA-014, and to the BSA Officer where the filing has
        already been released. Quality control reviewers do not amend
        narratives themselves; the case is returned to the investigator.
    """),
    _s("QC-009", "1.7", "6.0", "Documentation and Audit Trail", """
        Every quality control review is recorded in the case management system
        with the checklist outcome, any defects identified, the disposition and
        the reviewer's identity. The record is retained for five years
        alongside the filing and its supporting documentation, and is produced
        to internal audit and to examiners on request. An undocumented review
        is treated as a review that did not occur.
    """),
)

# --------------------------------------------------------------------------
# QC-022 v1.2 -- restricted
# --------------------------------------------------------------------------

_QC_22 = (
    _s("QC-022", "1.2", "1.0", "Law Enforcement Liaison", """
        All contact with law enforcement regarding a filed suspicious activity
        report is conducted by the BSA Officer or a named delegate. Analysts
        receiving direct contact from a law enforcement officer refer the
        contact to the BSA Officer without confirming or denying the existence
        of any filing.
    """, audience=("aml-manager", "bsa-officer")),
    _s("QC-022", "1.2", "2.0", "Subpoena and Grand Jury Request Handling", """
        Subpoenas and grand jury requests are logged on receipt and referred to
        Legal within one business day. Receipt of a subpoena concerning a
        customer is itself a factor to be considered in suspicious activity
        analysis, but is not alone a basis for filing. Account closure
        following a subpoena requires BSA Officer approval.
    """, audience=("aml-manager", "bsa-officer")),
)

SECTIONS: tuple[Section, ...] = _BSA_42 + _BSA_41 + _QA_21 + _QC_17 + _QC_22


def documents_by_key() -> dict[tuple[str, str], Document]:
    """Documents keyed by (policy_id, version)."""
    return {(d.policy_id, d.version): d for d in DOCUMENTS}


def version_of(section_id: str) -> str:
    """Pull the version out of a section id of the form POLICY@VERSION#NUMBER."""
    _, _, rest = section_id.partition("@")
    version, _, _ = rest.partition("#")
    return version


def pairs() -> list[tuple[Section, Document]]:
    """Every section with the document it belongs to."""
    index = documents_by_key()
    out: list[tuple[Section, Document]] = []
    for section in SECTIONS:
        document = index[(section.policy_id, version_of(section.section_id))]
        out.append((section, document))
    return out
