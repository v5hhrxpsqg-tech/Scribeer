import "jsr:@supabase/functions-js/edge-runtime.d.ts"
import { createClient } from "https://esm.sh/@supabase/supabase-js@2"
import Stripe from "https://esm.sh/stripe@14.14.0?target=deno"

const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY") || "", {
  apiVersion: "2023-10-16",
  httpClient: Stripe.createFetchHttpClient(),
})

const supabaseUrl = Deno.env.get("SUPABASE_URL") || ""
const supabaseServiceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || ""

// Product ID naar minuten mapping (pas aan naar jouw Stripe product IDs)
const PRODUCT_CREDITS: Record<string, number> = {
  // Voeg hier je Stripe Price IDs toe nadat je ze hebt
  // Format: "price_xxxxx": minuten
}

// Prijs naar minuten mapping (fallback op basis van bedrag in centen)
const PRICE_TO_CREDITS: Record<number, number> = {
  499: 100,    // €4.99 = 100 minuten
  1199: 300,   // €11.99 = 300 minuten
  1599: 500,   // €15.99 = 500 minuten
}

Deno.serve(async (req) => {
  const signature = req.headers.get("stripe-signature")
  const webhookSecret = Deno.env.get("STRIPE_WEBHOOK_SECRET")

  if (!signature || !webhookSecret) {
    console.error("Missing signature or webhook secret")
    return new Response("Missing signature", { status: 400 })
  }

  try {
    const body = await req.text()

    // Verify webhook signature (async version required for Deno)
    const event = await stripe.webhooks.constructEventAsync(body, signature, webhookSecret)

    console.log(`Received event: ${event.type}`)

    // Handle successful payment
    if (event.type === "checkout.session.completed" || event.type === "payment_intent.succeeded") {
      let customerEmail: string | null = null
      let amountPaid = 0
      let priceId: string | null = null

      if (event.type === "checkout.session.completed") {
        const session = event.data.object as Stripe.Checkout.Session
        customerEmail = session.customer_details?.email || session.customer_email
        amountPaid = session.amount_total || 0

        // Probeer price ID te krijgen van line items
        if (session.line_items?.data?.[0]?.price?.id) {
          priceId = session.line_items.data[0].price.id
        }
      } else {
        const paymentIntent = event.data.object as Stripe.PaymentIntent
        customerEmail = paymentIntent.receipt_email
        amountPaid = paymentIntent.amount
      }

      if (!customerEmail) {
        console.error("No customer email found")
        return new Response("No customer email", { status: 400 })
      }

      // Bepaal credits op basis van price ID of bedrag
      let creditsToAdd = 0
      if (priceId && PRODUCT_CREDITS[priceId]) {
        creditsToAdd = PRODUCT_CREDITS[priceId]
      } else {
        // Fallback: bepaal op basis van bedrag
        creditsToAdd = PRICE_TO_CREDITS[amountPaid] || 0
      }

      if (creditsToAdd === 0) {
        console.error(`Unknown amount: ${amountPaid} cents`)
        return new Response("Unknown product amount", { status: 400 })
      }

      console.log(`Adding ${creditsToAdd} minutes to ${customerEmail}`)

      // Connect to Supabase with service role key
      const supabase = createClient(supabaseUrl, supabaseServiceKey)

      // Check of user bestaat
      const { data: existingUser } = await supabase
        .from("user_credits")
        .select("credits_remaining_mb")
        .eq("email", customerEmail)
        .single()

      if (existingUser) {
        // Update bestaande user
        const newBalance = parseFloat(existingUser.credits_remaining_mb) + creditsToAdd
        const { error } = await supabase
          .from("user_credits")
          .update({
            credits_remaining_mb: newBalance,
            last_used: new Date().toISOString()
          })
          .eq("email", customerEmail)

        if (error) {
          console.error("Error updating credits:", error)
          return new Response("Database error", { status: 500 })
        }

        console.log(`Updated ${customerEmail}: +${creditsToAdd} = ${newBalance} minutes`)
      } else {
        // Maak nieuwe user aan met gekochte credits + 50 bonus
        const { error } = await supabase
          .from("user_credits")
          .insert({
            email: customerEmail,
            credits_remaining_mb: 50 + creditsToAdd
          })

        if (error) {
          console.error("Error creating user:", error)
          return new Response("Database error", { status: 500 })
        }

        console.log(`Created ${customerEmail} with ${50 + creditsToAdd} minutes`)
      }

      return new Response(JSON.stringify({ received: true, credits_added: creditsToAdd }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      })
    }

    // Return 200 for other event types
    return new Response(JSON.stringify({ received: true }), {
      headers: { "Content-Type": "application/json" },
      status: 200,
    })

  } catch (err) {
    console.error("Webhook error:", err)
    return new Response(`Webhook Error: ${err.message}`, { status: 400 })
  }
})
