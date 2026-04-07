## 3.1. General rules

* All requests and responses are in JSON format.
* There is only one currency for simplicity: `"EUR"`.
* The balance cannot be negative.
* A user cannot transfer money to themselves.
* There is a daily limit:

  * no more than 5 outgoing transfers per calendar day per sender user;
  * no more than 5,000 EUR of outgoing transfers per calendar day per sender user.

## 3.2. API endpoints

### 3.2.1. Create user

**POST** `/users`

**Request example:**

```json
{
  "name": "Alice",
  "email": "alice@example.com"
}
```

**Rules:**

* `name`: required, string 1–100 characters.
* `email`: required, string, must be unique in the system and have a valid email format.

**Successful response (201):**

```json
{
  "userId": "u-1001",
  "name": "Alice",
  "email": "alice@example.com"
}
```

**Error responses:**

* `400` — invalid data (e.g. empty name, invalid email format)
* `409` — email already exists

### 3.2.2. Deposit (top up balance)

**POST** `/wallets/deposit`

**Request example:**

```json
{
  "userId": "u-1001",
  "amount": 100.50,
  "currency": "EUR"
}
```

**Rules:**

* `userId`: required, must refer to an existing user.
* `amount`: required, number > 0, up to two decimal places.
* `currency`: currently only `"EUR"` is supported.

**Successful response (200):**

```json
{
  "userId": "u-1001",
  "newBalance": 100.50,
  "currency": "EUR"
}
```

**Error responses:**

* `400` — invalid data (negative or zero amount, wrong amount format, unsupported currency)
* `404` — user not found

### 3.2.3. Transfer between users

**POST** `/wallets/transfer`

**Request example:**

```json
{
  "senderId": "u-1001",
  "receiverId": "u-1002",
  "amount": 30.00,
  "currency": "EUR",
  "comment": "Dinner"
}
```

**Rules:**

* `senderId` and `receiverId`: required, both users must exist.
* `senderId ≠ receiverId` (self-transfers are not allowed).
* `amount`: number > 0, up to two decimal places.
* After the transfer, the sender’s balance must not become negative.
* Daily limits for the sender:

  * no more than 5 outgoing transfers per calendar day;
  * total outgoing amount per calendar day ≤ 5,000 EUR.

**Successful response (200):**

```json
{
  "operationId": "tr-9001",
  "status": "SUCCESS",
  "senderId": "u-1001",
  "receiverId": "u-1002",
  "amount": 30.00,
  "currency": "EUR"
}
```

**Error responses:**

* `400` — invalid data (senderId = receiverId, amount ≤ 0, unsupported currency)
* `402` — insufficient funds on the sender’s account
* `403` — daily limit on number of operations exceeded
* `429` — daily amount limit exceeded
* `404` — sender or receiver not found

### 3.2.4. Transaction history

**GET** `/wallets/{userId}/transactions?limit=20&offset=0`

**Parameters:**

* `userId` — user identifier.
* `limit` — how many records to return (default 20, maximum 100).
* `offset` — offset for pagination.

**Successful response (200):**

```json
{
  "userId": "u-1001",
  "transactions": [
    {
      "operationId": "tr-9001",
      "type": "OUTGOING",
      "amount": 30.00,
      "currency": "EUR",
      "timestamp": "2026-03-24T10:15:00Z",
      "counterpartyId": "u-1002",
      "comment": "Dinner"
    },
    {
      "operationId": "tr-9002",
      "type": "INCOMING",
      "amount": 50.00,
      "currency": "EUR",
      "timestamp": "2026-03-24T11:00:00Z",
      "counterpartyId": "u-1003",
      "comment": "Gift"
    }
  ]
}
```

**Error responses:**

* `400` — invalid limit/offset parameters
* `404` — user not found

## 3.3. Sample initial data
Assume the system already has the following users and balances:
u-1001: Alice, balance 100.00 EUR
u-1002: Bob, balance 20.00 EUR
u-1003: Carol, balance 0.00 EUR