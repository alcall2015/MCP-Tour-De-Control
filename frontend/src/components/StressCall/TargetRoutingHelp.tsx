/**
 * Explains how to configure the tested SIP server/provider so calls loop
 * back to this tester's built-in UAS (auto-answer on port 5080).
 */
export function TargetRoutingHelp() {
  return (
    <details
      className="rounded-xl px-4 py-3 text-sm"
      style={{
        backgroundColor: "var(--bg-elevated)",
        border: "1px solid var(--border)",
        color: "var(--text-secondary)",
      }}
    >
      <summary
        className="cursor-pointer text-xs font-medium uppercase tracking-wider"
        style={{ color: "var(--text-muted)" }}
      >
        How to route the call back (target server config)
      </summary>

      <div className="mt-3 space-y-3 text-xs leading-relaxed">
        <p>
          A test runs two SIPp processes on <strong>this</strong> server: a
          caller (UAC, source port <code>5070</code>) that sends calls to your
          target, and an auto-answering receiver (UAS, port{" "}
          <code>5080</code>). The UAS only listens while a test is running: it
          replies <code>180 Ringing</code>, answers with <code>200 OK</code>{" "}
          after 500&nbsp;ms, plays the selected media, and hangs up on BYE.
        </p>

        <p>
          <strong>Two test modes:</strong>
        </p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <strong>Target answers itself</strong> (IVR, echo, announcement,
            AI agent): nothing to configure — aim the target host/port at that
            application.
          </li>
          <li>
            <strong>Loop-back through the target</strong> (2 call legs, full
            media path): configure the target to route the called number back
            to this server&apos;s UAS at{" "}
            <code>sip:&lt;THIS_SERVER_IP&gt;:5080</code>.
          </li>
        </ul>

        <div>
          <p style={{ color: "var(--text-muted)" }}>
            Kamailio example — SIPp dials user <code>service</code> by
            default:
          </p>
          <pre
            className="mt-1 overflow-x-auto rounded-lg p-3"
            style={{
              backgroundColor: "var(--bg-primary)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          >
{`# Return stress-test calls to the tester UAS
if ($rU == "service") {
    rewritehostport("<THIS_SERVER_IP>:5080");
    t_relay();
    exit;
}`}
          </pre>
        </div>

        <div>
          <p style={{ color: "var(--text-muted)" }}>Asterisk/FreePBX target:</p>
          <pre
            className="mt-1 overflow-x-auto rounded-lg p-3"
            style={{
              backgroundColor: "var(--bg-primary)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          >
{`# pjsip.conf
[tester-uas]
type=endpoint
context=default
disallow=all
allow=alaw,ulaw
aors=tester-uas

[tester-uas]
type=aor
contact=sip:<THIS_SERVER_IP>:5080

; extensions.conf — send the call back to the tester
exten => service,1,Dial(PJSIP/service@tester-uas)`}
          </pre>
        </div>

        <p>
          Media: the UAS sends RTP from UDP ports <code>21000+</code> and the
          UAC from <code>26000+</code> — allow those ranges back from the
          target (e.g. through RTPEngine) for two-way audio.
        </p>
      </div>
    </details>
  );
}
