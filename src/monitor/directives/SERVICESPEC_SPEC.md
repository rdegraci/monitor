# Service Test Specification (Combine, Quick/Nimble, OHHTTPStubs)

## Purpose
This specification describes how to write a service unit test (“Spec”) that verifies:
- Correct usage of a Combine-based Service for a specific Model.
- Proper endpoint usage (URL/method), decoding, and error handling.
- Use of Quick/Nimble-style structure and OHHTTPStubs for network stubbing.

---

## Setup

- Use Quick as the spec framework and Nimble for assertions.
- Use OHHTTPStubs for HTTP request interception and response stubbing.
- Use Combine for publisher/subscriber patterns.
- Use an appropriate means to decode and check your Model.

---

## Specification Structure

### 1. Imports

```swift
import AppCore
import Combine
import Cuckoo
@testable import <YourAppModule>
import Nimble
import OHHTTPStubs
import Quick
```

---

### 2. Spec Class Definition

Use the naming convention: `ModelNameServiceSpec: QuickSpec`

### 3. Top-level describe/context blocks

- Describe the service under test and its primary methods (usually `fetch`).

---

### 4. Before/After Setup

- Register and remove network stubs before/after each test context.
- Create a variable for cancellables for publisher subscriptions.

---

## Test Cases to Cover

### a. Successful Fetch (all fields)
- Stub API to return a JSON fixture with all fields.
- Assert request URL and HTTP method.
- Assert all fields in the resulting model.

### b. Successful Fetch (minimal fields)
- Stub API to return minimal JSON fixture.
- Assert required fields, and optionals as nil/unset.

### c. Network Failure
- Stub API to return a network error.
- Assert the Combine publisher completes with the expected error.

### d. Decoding Failure
- Stub API to return malformed/incompatible JSON.
- Assert Combine publisher completes with a DecodingError.

### e. Configuration Error (if service configures endpoint at init)
- Initialize the service improperly (e.g., missing URL).
- Assert publisher completes with a configuration error.

---

## Example Code Template

```swift
class ModelNameServiceSpec: QuickSpec {
    override class func spec() {
        // Define endpoint matcher for used host
        let apiMatcher: HTTPStubsTestBlock = isHost("example.com")
        var subject: ModelNameService!
        var cancellables: Set<AnyCancellable>!

        describe("ModelNameService") {
            beforeEach {
                registerUnpermittedStub(condition: !apiMatcher)
                HTTPStubs.removeAllStubs()
                cancellables = []
                // If using DI/config
                // subject = ModelNameService(properties: ["details_url": "https://example.com/aoi"])
                // If stateless service
                // subject = ModelNameService()
            }

            afterEach {
                HTTPStubs.removeAllStubs()
                cancellables = nil
            }

            describe("fetch") {
                context("when fetch succeeds with full response") {
                    it("parses all properties correctly") {
                        let url = URL(string: "https://example.com/<endpoint>")!
                        stub(condition: apiMatcher) { request in
                            expect(request.url!.absoluteString).to(equal(url.absoluteString))
                            expect(request.httpMethod).to(equal("GET"))
                            return jsonFixture(file: "full_model.json")
                        }
                        var received: ModelName?
                        var receivedError: Error?
                        waitUntil(timeout: .seconds(3)) { done in
                            subject.fetch(url: url).sink(
                                receiveCompletion: { completion in
                                    if case .failure(let error) = completion {
                                        receivedError = error
                                    }
                                    done()
                                },
                                receiveValue: { value in
                                    received = value
                                }
                            ).store(in: &cancellables)
                        }
                        expect(receivedError).to(beNil())
                        expect(received).toNot(beNil())
                        // Detailed model field assertions here
                        // Example:
                        // expect(received?.name) == "Central Park"
                    }
                }

                context("when fetch succeeds with minimal JSON") {
                    it("parses required fields and sets optionals nil") {
                        let url = URL(string: "https://example.com/<endpoint-minimal>")!
                        stub(condition: apiMatcher) { _ in
                            return jsonFixture(file: "minimal_model.json")
                        }
                        var received: ModelName?
                        waitUntil(timeout: .seconds(3)) { done in
                            subject.fetch(url: url).sink(
                                receiveCompletion: { _ in done() },
                                receiveValue: { value in received = value }
                            ).store(in: &cancellables)
                        }
                        // Assert only required fields set
                        // Example:
                        // expect(received?.id) == "123"
                        // expect(received?.optionalField).to(beNil())
                    }
                }

                context("when fetch fails with network error") {
                    it("propagates the error") {
                        let url = URL(string: "https://example.com/network-error")!
                        stub(condition: apiMatcher) { _ in
                            let error = NSError(domain: NSURLErrorDomain, code: NSURLErrorNotConnectedToInternet)
                            return HTTPStubsResponse(error: error)
                        }
                        var receivedError: Error?
                        waitUntil(timeout: .seconds(3)) { done in
                            subject.fetch(url: url).sink(
                                receiveCompletion: { completion in
                                    if case .failure(let err) = completion {
                                        receivedError = err
                                    }
                                    done()
                                },
                                receiveValue: { _ in }
                            ).store(in: &cancellables)
                        }
                        expect(receivedError).toNot(beNil())
                        // Optionally: expect((receivedError as NSError?)?.code) == NSURLErrorNotConnectedToInternet
                    }
                }

                context("when fetch returns malformed JSON") {
                    it("fails with decoding error") {
                        let url = URL(string: "https://example.com/malformed")!
                        stub(condition: apiMatcher) { _ in
                            let malformedJSON = "{ not valid! }".data(using: .utf8)!
                            return HTTPStubsResponse(data: malformedJSON, statusCode: 200, headers: ["Content-Type": "application/json"])
                        }
                        var receivedError: Error?
                        waitUntil(timeout: .seconds(3)) { done in
                            subject.fetch(url: url).sink(
                                receiveCompletion: { completion in
                                    if case .failure(let err) = completion {
                                        receivedError = err
                                    }
                                    done()
                                },
                                receiveValue: { _ in }
                            ).store(in: &cancellables)
                        }
                        expect(receivedError).to(beAKindOf(DecodingError.self))
                    }
                }

                // Only needed if Service takes configuration at init
                context("when service is misconfigured") {
                    it("fails with configuration error") {
                        // subject = ModelNameService(properties: [:]) // Intentionally missing properties
                        var receivedError: Error?
                        waitUntil(timeout: .seconds(3)) { done in
                            subject.fetch(url: nil).sink(
                                receiveCompletion: { completion in
                                    if case .failure(let err) = completion {
                                        receivedError = err
                                    }
                                    done()
                                },
                                receiveValue: { _ in }
                            ).store(in: &cancellables)
                        }
                        // expect(receivedError).to(beAKindOf(ModelNameService.ServiceError.self))
                    }
                }
            }
        }
    }
}
```

---

## Notes

- Substitute `ModelName`, `ModelNameService`, and appropriate URLs/fixtures for your actual models and network setup.
- Add/remove test cases depending on your Service’s public API (non-URL config, error modes, etc).

---

This template will generate specs with the same logic, style, and level of thoroughness for any Combine-based Service as in your project.
