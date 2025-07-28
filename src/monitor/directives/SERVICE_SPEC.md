# Service Class Specification (Combine Pattern)

## Purpose

A `Service` class manages fetching, creating, updating, or deleting a given Model from a RESTful endpoint. The Service exposes a single asynchronous API method using Combine publishers, and internally manages all endpoint, request, and decoding details.

---

## Intended Usage

1. A developer or LLM is provided with this template and actual Model code.
2. The Service’s code is generated specifically for that Model, naming and plugging in all type references as needed (e.g. `WeatherAlert`, `UserProfile`).
3. The concrete Service class does **not** use generics and exposes Combine’s publisher API.

---

## Initialization

```swift
init(properties: [AnyHashable: Any])
```
- `properties`: Dictionary used to provide configuration (e.g., URL String, endpoint details, headers, and/or decoding context).

---

## Public API

The Service exposes **one** main instance method corresponding to the CRUD operation and acting on the Model type.  
The function returns a Combine publisher, which yields the decoded Model or an Error.

For fetching (read) pattern:

```swift
func fetch([parameters]) -> AnyPublisher<ModelName, Error>
```
Possible parameter(s): e.g. `id: String` (you may omit parameters if fetching a collection or configuration alone is sufficient).

---

## Implementation Details

- **Request Building:** All endpoint URL construction, parameterization, and HTTP method choices are handled internally and are never exposed.
- **Decoder Customization:** The Service may use a private method to build a JSONDecoder (optionally injecting values via `userInfo`).
- **Error Handling:** Service must define a clearly-scoped error enum for logical errors (e.g. misconfiguration), with all networking/decoding errors passed through “as is.”
- **Combine Publisher:** The public endpoint ALWAYS returns a Combine publisher (AnyPublisher<ModelName, Error>), never a callback or async/await.

---

## Example Class Skeleton

This is the pattern to follow (llm: substitute `ModelName` with the provided Model class/struct):

```swift
import Foundation
import Combine

class ModelNameService {
    enum ModelNameServiceError: Error {
        case missingURL
        case invalidURL(url: String)
        // add further error cases as needed

        // Optionally: add logging/error code properties
    }

    private var properties: [AnyHashable: Any]

    init(properties: [AnyHashable: Any]) {
        self.properties = properties
    }

    func fetch([parameters]) -> AnyPublisher<ModelName, Error> {
        // Example pattern:
        guard let urlString = properties["details_url"] as? String else {
            return Fail(error: ModelNameServiceError.missingURL)
                .eraseToAnyPublisher()
        }
        guard let url = URL(string: urlString) else {
            return Fail(error: ModelNameServiceError.invalidURL(url: urlString))
                .eraseToAnyPublisher()
        }
        let endpoint = Endpoint(url: url, httpMethod: .GET)
        let decoder = buildDecoder()
        return endpoint.requestPublisher()
            .decode(type: ModelName.self, decoder: decoder)
            .eraseToAnyPublisher()
    }

    private func buildDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        // Add CodingUserInfoKey logic if needed for ModelName
        return decoder
    }
}
```

---

## Testing Guidance

- Stubbing with e.g. OHHTTPStubs should be used to assert the outgoing request details (URL, headers, body, etc).
- Negative tests should verify correct error propagation for all failure modes (invalid config, network errors, decoding errors).

---

## Model Substitution

Whenever generating a concrete service, substitute all instances of `ModelName` with the actual Model type/class (e.g., `WeatherAlert`).

---

## LLM Generation Guidance

- Do **not** use generics.
- Use Combine (`AnyPublisher<ModelName, Error>`).
- Expose one main function (`fetch`, `create`, `update`, or `destroy`), using REST/CRUD naming conventions.
- All networking and decoding happens inside the Service.
- Document all class members, errors, and main public function with Swift doc comments.

---

If you would like a fully worked-out example with a real model, just provide the Model code and endpoint details!
