import { Clerk } from "@clerk/clerk-js";

const clerkPubKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

if (!clerkPubKey) {
  document.getElementById("app").innerHTML = `
    <div class="error">
      <h2>Missing Clerk publishable key</h2>
      <p>Set <code>VITE_CLERK_PUBLISHABLE_KEY</code> in <code>.env</code> then restart <code>npm run dev</code>.</p>
    </div>
  `;
  throw new Error("Missing VITE_CLERK_PUBLISHABLE_KEY env var");
}

const clerk = new Clerk(clerkPubKey);
await clerk.load();

const app = document.getElementById("app");

function render() {
  if (clerk.isSignedIn) {
    const user = clerk.user;
    app.innerHTML = `
      <div class="authed">
        <h1>Welcome, ${user.firstName ?? "Friend"}!</h1>
        <p>You are signed in. Use the button below to manage your account.</p>
        <div id="user-button"></div>
        <div class="token-box">
          <button id="copy-token">Copy session token</button>
          <p class="hint">Use this token as <code>Authorization: Bearer &lt;token&gt;</code> when calling the Flask API.</p>
          <pre id="token-value"></pre>
        </div>
      </div>
    `;
    const userButton = document.getElementById("user-button");
    clerk.mountUserButton(userButton, { appearance: { elements: { rootBox: "user-button" } } });

    const btn = document.getElementById("copy-token");
    const tokenValue = document.getElementById("token-value");
    btn.addEventListener("click", async () => {
      const token = await clerk.session.getToken({ template: "default" });
      if (token) {
        await navigator.clipboard.writeText(token);
        tokenValue.textContent = token;
        btn.textContent = "Copied!";
        setTimeout(() => (btn.textContent = "Copy session token"), 2000);
      }
    });
  } else {
    app.innerHTML = `
      <div class="sign-in-container">
        <div id="sign-in"></div>
      </div>
    `;
    const signInDiv = document.getElementById("sign-in");
    clerk.mountSignIn(signInDiv, {
      appearance: {
        elements: {
          card: "card",
          formButtonPrimary: "primary-button"
        }
      }
    });
  }
}

clerk.addListener(render);
render();
