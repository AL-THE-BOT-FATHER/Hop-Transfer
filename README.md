## Transfer Hop

A lightweight Python utility for reliably moving SOL through a temporary “hop” account: 

it auto-generates and persists a hop keypair,

funds the hop (with a fee cushion),

forwards the desired amount to your recipient,

and then recovers any leftover back to the sender—

all with built-in retries, on-chain confirmations, and automatic hop-key persistence.
